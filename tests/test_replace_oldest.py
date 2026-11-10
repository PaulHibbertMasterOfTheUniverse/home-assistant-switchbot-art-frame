"""Execute staged production recovery/manager methods with a fake clock and API.

No HA instance, credentials, network, user artwork or real sleeps are used.
"""
import ast
import asyncio
import copy
import hashlib
import importlib.util
import io
import json
import os
import binascii
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, Mock

from PIL import Image, ImageOps, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / 'custom_components/switchbot_frame_control'
PACKAGE = 'review_frame'
package = types.ModuleType(PACKAGE)
package.__path__ = [str(CODE)]
sys.modules[PACKAGE] = package


def load(name):
    spec = importlib.util.spec_from_file_location(PACKAGE + '.' + name, CODE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


protocol = load('protocol')
recovery = load('replacement')
FrameError = protocol.FrameError
native = types.ModuleType(PACKAGE + '.native_image')
native.cloud_assets = lambda *args: (b'jpeg', b'thumbnail', b'bin')
sys.modules[native.__name__] = native
tree = ast.parse((CODE / '__init__.py').read_text())
nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))
         and node.name in ('Manager', 'FrameRegistry', 'jpeg_bytes', 'UploadView', 'FramesView')]
scope = dict(__name__=PACKAGE + '.manager', __package__=PACKAGE,
             asyncio=asyncio, hashlib=hashlib, json=json, Path=Path, io=io, os=os, binascii=binascii,
             Image=Image, ImageOps=ImageOps, UnidentifiedImageError=UnidentifiedImageError,
             MAX_FILE=8*1024*1024, FrameError=FrameError, Replacement=recovery.Replacement,
             callback=lambda f: f, HomeAssistantView=object, DOMAIN='switchbot_frame_control')
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(CODE / '__init__.py'), 'exec'), scope)
Manager = scope['Manager']


class Clock:
    now = 0

    async def sleep(self, seconds):
        self.now += seconds


class Store:
    def __init__(self):
        self.saved = {}
        self.fail = False

    async def async_save(self, data):
        if not self.fail:
            self.saved = copy.deepcopy(data)

    async def async_load(self):
        return copy.deepcopy(self.saved)


class Client:
    def __init__(self, clock):
        self.clock = clock
        self.device = 'synthetic-frame'
        self.group = 'synthetic-album'
        self.stored = set(range(1, 11))
        self.items = {i: {'imageIndex': i, 'createdAt': i + 100, 'mainImageUrl': f'https://example.invalid/{i}.jpg'}
                      for i in self.stored}
        self.items[3]['createdAt'] = 1
        self.events = []
        self.delay = 0
        self.remove_at = None
        self.cloud_stuck = False
        self.release_lost_reply = False
        self.unknown = False
        self.reuse_at = None
        self.registrations = 0
        self.upload_assets = AsyncMock(return_value=['main.jpg', 'thumb.jpg', 'bin.bin'])

    def tick(self):
        if self.remove_at is not None and self.clock.now >= self.remove_at:
            self.stored.discard(3)
        if self.reuse_at is not None and self.clock.now >= self.reuse_at:
            self.items[3] = {'imageIndex': 3, 'createdAt': 1, 'mainImageUrl': 'https://example.invalid/NEW.jpg'}
            self.stored.add(3)

    async def reported_state(self):
        self.tick()
        return {'9606': {'value': None if self.unknown else sorted(self.stored)}}

    async def catalogue(self):
        self.tick()
        return copy.deepcopy(list(self.items.values()))

    async def invoke(self, function, params=None):
        self.events.append((self.clock.now, function, params))
        if function == 9601:
            assert params == {'0': 2, '1': 3}, 'Deleted an unconfirmed slot'
            if self.remove_at is None:
                self.remove_at = self.clock.now + self.delay
            if self.release_lost_reply:
                self.release_lost_reply = False
                raise asyncio.TimeoutError()

    async def post(self, endpoint, params):
        self.events.append((self.clock.now, endpoint, copy.deepcopy(params)))
        assert params.get('imageIndexList', params.get('imageIndexes')) == [3]
        assert params['deleteAll'] is False
        if endpoint.endswith('/images/delete') and not self.cloud_stuck:
            self.items.pop(3, None)

    async def register_image(self, names):
        assert len(self.stored) < 10 and len(self.items) < 10, 'Registered without safe capacity'
        self.registrations += 1
        self.items[30] = {'imageIndex': 30, 'createdAt': 1000, 'mainImageUrl': 'https://example.invalid/main.jpg'}
        return 30


class ReplacementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = Clock()
        recovery.asyncio = types.SimpleNamespace(sleep=self.clock.sleep, TimeoutError=asyncio.TimeoutError)
        recovery.time = types.SimpleNamespace(time=lambda: self.clock.now)
        self.client = Client(self.clock)
        self.temp = tempfile.TemporaryDirectory(prefix='frame-review-', dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        manager = self.manager = Manager.__new__(Manager)
        manager.hass = types.SimpleNamespace(data={},config=types.SimpleNamespace(path=lambda *p: str(Path(self.temp.name).joinpath(*p))))

        async def executor(function, *args):
            return function(*args)

        manager.hass.async_add_executor_job = executor
        manager.config = {'model': 'frame1', 'connection_mode': 'wifi', 'credentials_file': 'not-read'}
        manager.data = {'baby_indices': [], 'normal_indices': list(range(1, 11)),
                        'cloud_art_uploads': {'old-digest': 3}, 'layout': {'orientation': 'portrait', 'flipped': False}}
        manager.frame_id = 'synthetic'
        manager.client = self.client
        manager.store = Store()
        manager.lock = asyncio.Lock()
        manager.error = None
        manager.publish = Mock()
        manager.desired = lambda: False
        manager.report_failure = AsyncMock()
        manager.read_image = AsyncMock(return_value=b'synthetic private backup')
        self.replacement = recovery.Replacement(manager)

    async def test_late_removal_after_120_seconds_recovers_automatically(self):
        self.client.delay = 135
        await self.replacement.prepare(3, 'new-digest')
        self.assertGreater(self.clock.now, 120)
        self.assertLessEqual(self.clock.now, 250)
        self.assertEqual(self.replacement.pending['stage'], 'capacity_confirmed')
        self.assertEqual(set(self.client.items), set(range(1, 11)) - {3})
        self.assertEqual(self.client.registrations, 0)
        self.assertNotIn('old-digest', self.manager.data['cloud_art_uploads'])
        self.manager.read_image.assert_awaited_once()
        self.assertEqual(self.replacement.pending['release_requests'], 2)

    async def test_timeout_preserves_verified_backup_and_pending_intent(self):
        self.client.delay = 9999
        with self.assertRaisesRegex(FrameError, 'two bounded'):
            await self.replacement.prepare(3, 'new-digest')
        self.assertEqual(self.clock.now, 250)
        saved = await self.manager.store.async_load()
        self.assertEqual(saved['pending_replacement']['stage'], 'capacity_timeout')
        self.assertEqual(saved['pending_replacement']['release_requests'], 2)
        await self.manager.verify_replacement_backup(saved['pending_replacement']['backup'])
        self.assertEqual(self.client.registrations, 0)

    async def test_restart_resume_after_late_removal_never_deletes_next_artwork(self):
        self.client.delay = 9999
        with self.assertRaises(FrameError):
            await self.replacement.prepare(3, 'new-digest')
        saved = await self.manager.store.async_load()
        before = copy.deepcopy(self.client.events)
        self.manager.data = saved  # Restart restores transaction using Store API.
        self.client.remove_at = self.clock.now
        await recovery.Replacement(self.manager).prepare(3, 'new-digest')
        self.assertEqual(self.client.events, before)
        self.assertEqual(self.manager.data['pending_replacement']['release_requests'], 2)

    async def test_resume_still_stuck_does_not_reset_command_budget(self):
        self.client.delay = 9999
        for _ in range(2):
            with self.assertRaises(FrameError):
                await self.replacement.prepare(3, 'new-digest')
        self.assertEqual(sum(event[1] == 9601 for event in self.client.events), 2)

    async def test_wrong_slot_or_changed_source_blocked_without_mutation(self):
        self.client.delay = 9999
        with self.assertRaises(FrameError):
            await self.replacement.prepare(3, 'new-digest')
        before = copy.deepcopy(self.client.events)
        for index, digest in [(4, 'new-digest'), (3, 'different-picture')]:
            with self.assertRaisesRegex(FrameError, 'different replacement'):
                await self.replacement.prepare(index, digest)
        self.assertEqual(before, self.client.events)

    async def test_changed_oldest_before_confirmation_never_deletes(self):
        with self.assertRaisesRegex(FrameError, 'oldest stored picture changed'):
            await self.replacement.prepare(4, 'new-digest')
        self.assertEqual(self.client.events, [])

    async def test_reused_slot_same_timestamp_different_object_never_deleted(self):
        self.client.delay = 9999
        with self.assertRaises(FrameError):
            await self.replacement.prepare(3, 'new-digest')
        self.client.reuse_at = self.clock.now
        before = copy.deepcopy(self.client.events)
        with self.assertRaisesRegex(FrameError, 'identity changed'):
            await self.replacement.prepare(3, 'new-digest')
        self.assertEqual(before, self.client.events)

    async def test_corrupt_backup_blocks_resumption_before_any_mutation(self):
        self.client.delay = 9999
        with self.assertRaises(FrameError):
            await self.replacement.prepare(3, 'new-digest')
        backup = self.replacement.pending['backup']
        Path(self.manager.hass.config.path('frame_art_archive', 'synthetic', backup['name'])).write_bytes(b'corrupt')
        before = copy.deepcopy(self.client.events)
        with self.assertRaisesRegex(FrameError, 'backup verification failed'):
            await self.replacement.prepare(3, 'new-digest')
        self.assertEqual(before, self.client.events)

    async def test_store_failure_blocks_all_deletion(self):
        self.manager.store.fail = True
        with self.assertRaisesRegex(FrameError, 'persistence'):
            await self.replacement.prepare(3, 'new-digest')
        self.assertEqual(self.client.events, [])

    async def test_unknown_device_capacity_fails_closed(self):
        self.client.unknown = True
        with self.assertRaises(FrameError):
            await self.replacement.prepare(3, 'new-digest')
        self.assertEqual(self.client.events, [])

    async def test_cloud_capacity_not_safe_prevents_registration(self):
        self.client.cloud_stuck = True
        digest = hashlib.sha256(b'synthetic-upload').hexdigest()
        with self.assertRaises(FrameError):
            await self.replacement.prepare(3, digest)
        with self.assertRaisesRegex(FrameError, 'not both confirmed'):
            await self.manager.cloud_art(b'synthetic-upload')
        self.assertEqual(self.client.registrations, 0)

    async def test_uncertain_release_reply_observed_without_another_slot_delete(self):
        self.client.release_lost_reply = True
        self.client.delay = 135
        await self.replacement.prepare(3, 'new-digest')
        self.assertNotIn(3, self.client.stored)
        self.assertTrue(all(event[2]['1'] == 3 for event in self.client.events if event[1] == 9601))

    async def test_duplicate_submit_reuses_registration_and_never_deletes_again(self):
        content = b'synthetic-upload'
        digest = hashlib.sha256(content).hexdigest()
        await self.replacement.prepare(3, digest)
        self.assertEqual(await self.manager.cloud_art(content), 30)
        self.assertIsNone(self.replacement.pending)
        before = copy.deepcopy(self.client.events)
        await self.replacement.prepare(3, digest)
        self.assertEqual(await self.manager.cloud_art(content), 30)
        self.assertEqual(self.client.registrations, 1)
        self.assertEqual(before, self.client.events)

    async def test_new_registration_capacity_rechecked_after_asset_uploads(self):
        content = b'synthetic-upload'
        digest = hashlib.sha256(content).hexdigest()
        await self.replacement.prepare(3, digest)

        async def fill_album(*args):
            self.client.items[40] = {'imageIndex': 40, 'createdAt': 2000}
            return ['main', 'thumbnail', 'bin']

        self.client.upload_assets.side_effect = fill_album
        with self.assertRaisesRegex(FrameError, 'not both confirmed'):
            await self.manager.cloud_art(content)
        self.assertEqual(self.client.registrations, 0)

    async def test_ambiguous_registration_blocks_retry_and_keeps_transaction(self):
        content = b'synthetic-upload'
        digest = hashlib.sha256(content).hexdigest()
        await self.replacement.prepare(3, digest)
        self.client.register_image = AsyncMock(side_effect=asyncio.TimeoutError())
        with self.assertRaises(asyncio.TimeoutError):
            await self.manager.cloud_art(content)
        self.assertIn('pending_cloud_registration', self.manager.data)
        before = copy.deepcopy(self.client.events)
        with self.assertRaisesRegex(FrameError, 'uncertain registration'):
            await self.replacement.prepare(3, digest)
        self.assertEqual(before, self.client.events)
        self.client.register_image.assert_awaited_once()

    async def test_upload_resumes_same_transaction_without_replace_index(self):
        image = Image.new('RGB', (8, 6), 'red')
        out = io.BytesIO(); image.save(out, 'JPEG'); raw = out.getvalue()
        digest = hashlib.sha256(scope['jpeg_bytes'](raw)).hexdigest()
        self.client.delay = 9999
        with self.assertRaises(FrameError):
            await self.replacement.prepare(3, digest)
        self.client.remove_at = self.clock.now

        async def deliver(content):
            return {'new_index': await self.manager.cloud_art(content)}

        self.manager.deliver_cloud_art = deliver
        result = await self.manager.upload(raw)
        self.assertEqual(result, {'new_index': 30})
        self.assertIsNone(self.replacement.pending)
        self.assertEqual(self.client.registrations, 1)

    async def test_one_upload_request_survives_late_removal_then_registers_once(self):
        image=Image.new('RGB',(8,6),'blue');out=io.BytesIO();image.save(out,'JPEG')
        self.client.delay=135

        async def deliver(content):return {'new_index':await self.manager.cloud_art(content)}

        self.manager.deliver_cloud_art=deliver
        result=await self.manager.upload(out.getvalue(),replace_index=3,
            expected_layout={'orientation':'portrait','flipped':False})
        self.assertEqual(result,{'new_index':30})
        self.assertGreater(self.clock.now,120)
        self.assertEqual(self.client.registrations,1)
        self.assertIsNone(self.replacement.pending)
        self.assertEqual(self.manager.data['last_replacement']['index'],3)

    async def test_stale_layout_rejected_before_backup_or_delivery(self):
        self.manager.data['layout'] = {'orientation': 'portrait', 'flipped': True}
        with self.assertRaisesRegex(FrameError, 'layout changed'):
            await self.manager.upload(b'not even decoded', expected_layout={'orientation': 'portrait', 'flipped': False})
        self.assertEqual(self.client.events, [])
        self.manager.read_image.assert_not_awaited()

    async def test_layout_service_manager_persists_only_target_and_increments_revision(self):
        self.manager.data['layout_revision'] = 2
        await self.manager.set_layout({'orientation': 'portrait', 'flipped': True})
        self.assertEqual(self.manager.data['layout_revision'], 3)
        self.assertEqual((await self.manager.store.async_load())['layout']['flipped'], True)
        await self.manager.set_layout({'orientation': 'portrait', 'flipped': True})
        self.assertEqual(self.manager.data['layout_revision'], 3)
        self.assertEqual(self.client.events, [])

    async def test_bin_notification_slot_is_not_eligible_for_replacement(self):
        self.manager.hass.data['frame_bin_reminder'] = types.SimpleNamespace(manager=self.manager,data={'slot':{'index':3}})
        with self.assertRaisesRegex(FrameError, 'oldest stored picture changed'):
            await self.replacement.prepare(3, 'new-digest')
        self.assertEqual(self.client.events, [])

    async def test_registration_intent_disk_failure_prevents_registration(self):
        content=b'synthetic-upload';digest=hashlib.sha256(content).hexdigest()
        await self.replacement.prepare(3,digest)
        original=self.manager.save

        async def fail_registration_marker():
            if self.manager.data.get('pending_cloud_registration'):
                self.manager.store.fail=True
            await original()

        self.manager.save=fail_registration_marker
        with self.assertRaisesRegex(FrameError,'persistence'):
            await self.manager.cloud_art(content)
        self.assertEqual(self.client.registrations,0)

    async def test_stale_browser_cannot_overwrite_new_service_layout(self):
        await self.manager.set_layout({'orientation':'portrait','flipped':True})
        with self.assertRaisesRegex(FrameError,'another session'):
            await self.manager.set_layout({'orientation':'portrait','flipped':False},expected_revision=0)
        self.assertTrue(self.manager.data['layout']['flipped'])

    async def test_failed_layout_persistence_restores_previous_in_memory_layout(self):
        self.manager.store.fail=True
        with self.assertRaisesRegex(FrameError,'persistence'):
            await self.manager.set_layout({'orientation':'portrait','flipped':True})
        self.assertFalse(self.manager.data['layout']['flipped'])
        self.assertEqual(self.manager.data['layout_revision'],0)

    async def test_reconcile_lost_registration_then_resume_never_deletes(self):
        content=b'synthetic-upload';digest=hashlib.sha256(content).hexdigest()
        await self.replacement.prepare(3,digest)
        self.manager.data['pending_cloud_registration']={'sha256':digest,'files':['new-main.jpg','thumb','bin']}
        self.client.items[30]={'imageIndex':30,'createdAt':1000,'mainImageUrl':'https://example.invalid/new-main.jpg'}
        await self.manager.reconcile_registration()
        before=copy.deepcopy(self.client.events)
        await self.replacement.prepare(3,digest)
        self.assertEqual(await self.manager.cloud_art(content),30)
        self.assertEqual(before,self.client.events)
        self.assertIsNone(self.replacement.pending)
        self.assertEqual(self.client.registrations,0)

    async def test_backup_not_replaced_by_a_later_manual_backup(self):
        self.client.delay=9999
        with self.assertRaises(FrameError):await self.replacement.prepare(3,'new-digest')
        original_backup=dict(self.replacement.pending['backup'])
        self.manager.data['last_archived_art']={'index':4,'name':'another-backup.jpg','sha256':'not-used'}
        self.client.remove_at=self.clock.now
        await self.replacement.prepare(3,'new-digest')
        self.assertEqual(self.replacement.pending['backup'],original_backup)

    async def test_registered_layout_service_routes_only_the_named_frame(self):
        setup=next(node for node in tree.body if isinstance(node,ast.AsyncFunctionDef) and node.name=='async_setup')
        functions=[node for node in setup.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in ('target','set_layout')]
        other=types.SimpleNamespace(data={'layout':{'orientation':'portrait','flipped':False}},set_layout=AsyncMock())
        registry=scope['FrameRegistry'](self.manager.hass,{'example_frame':self.manager,'ready_room':other})
        service_scope={'registry':registry,'FrameError':FrameError,'HomeAssistantError':FrameError}
        exec(compile(ast.Module(body=functions,type_ignores=[]),'staged-layout-service','exec'),service_scope)
        await service_scope['set_layout'](types.SimpleNamespace(data={'frame_id':'example_frame','orientation':'portrait','flipped':True}))
        self.assertTrue(self.manager.data['layout']['flipped'])
        self.assertFalse(other.data['layout']['flipped'])
        other.set_layout.assert_not_awaited()


class ViewGuardsTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_cached_card_upload_without_layout_is_rejected(self):
        manager=types.SimpleNamespace(upload=AsyncMock(),report_failure=AsyncMock())
        registry=types.SimpleNamespace(select=lambda _:manager)
        request=types.SimpleNamespace(content_length=100,json=AsyncMock(return_value={'frame_id':'synthetic','image':'eA=='}),
                                      get=lambda _:types.SimpleNamespace(is_admin=True))
        scope['base64']=__import__('base64')
        scope['web']=types.SimpleNamespace(json_response=lambda data,status=200:(data,status))
        response,status=await scope['UploadView'](registry).post(request)
        self.assertEqual(status,400)
        self.assertIn('Reload this dashboard',response['error'])
        manager.upload.assert_not_awaited()

    async def test_old_cached_card_cannot_save_layout_without_revision(self):
        manager=types.SimpleNamespace(set_layout=AsyncMock())
        registry=types.SimpleNamespace(select=lambda _:manager)
        request=types.SimpleNamespace(json=AsyncMock(return_value={'frame_id':'synthetic','layout':{'orientation':'portrait','flipped':False}}),
                                      get=lambda _:types.SimpleNamespace(is_admin=True))
        scope['web']=types.SimpleNamespace(json_response=lambda data,status=200:(data,status))
        response,status=await scope['FramesView'](registry).post(request)
        self.assertEqual(status,400)
        self.assertIn('Reload this dashboard',response['error'])
        manager.set_layout.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
