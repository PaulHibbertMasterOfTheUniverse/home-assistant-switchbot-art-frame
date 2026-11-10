"""Exercise installed methods with synthetic clients; no HA/network/credentials."""
import ast
import asyncio
import time
import unittest
from contextlib import AsyncExitStack
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1] / 'custom_components'


class FrameError(Exception):
    pass


def method(path, name, **namespace):
    source=ROOT/path
    if path.startswith('frame_bin_reminder/'):
        source=ROOT.parent/'extras'/path
    tree = ast.parse(source.read_text())
    matches = [n for cls in tree.body if isinstance(cls, ast.ClassDef)
               for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name]
    assert len(matches) == 1
    module = ast.fix_missing_locations(ast.Module(body=matches, type_ignores=[]))
    scope = {'FrameError': FrameError, 'HomeAssistantError': FrameError,
             'asyncio': NS(sleep=AsyncMock(), TimeoutError=asyncio.TimeoutError), 'AsyncExitStack': AsyncExitStack,
             'dt_util': NS(now=lambda: datetime.now(timezone.utc)), 'timedelta': timedelta,
             'time': time,
             **namespace}
    exec(compile(module, str(ROOT / path), 'exec'), scope)
    return scope[name]


class RefreshTests(unittest.IsolatedAsyncioTestCase):
    async def client(self, states, images=None):
        events = []
        pending = list(states)

        async def invoke(*args):
            events.append(('invoke', args))

        async def state():
            value = pending.pop(0) if pending else states[-1]
            events.append(('state', value))
            return value

        async def sleep(seconds):
            events.append(('sleep', seconds))

        client = NS(catalogue=AsyncMock(return_value=[{'imageIndex': 83}] if images is None else images),
                    invoke=invoke, reported_state=state)
        show = method('switchbot_frame_control/protocol.py', 'show')
        client.show = lambda *args: show(client, *args)
        refresh = method('switchbot_frame_control/protocol.py', 'refresh_image', asyncio=NS(sleep=sleep))
        return lambda trace=None: refresh(client, 83, trace=trace), events

    async def test_exact_cycle_waits_through_stale_lists(self):
        present = {'9606': {'value': [83, 100]}}
        absent = {'9606': {'value': [100]}}
        refresh, events = await self.client([present] * 4 + [absent] * 18 + [present])
        await refresh()
        commands = [e[1] for e in events if e[0] == 'invoke']
        self.assertEqual(commands, [(9609,), (9601, {'0': 2, '1': 83}), (9609,),
                                    (9601, {'0': 1, '1': 83}), (9602, {'0': 83})])
        sleeps = [e[1] for e in events if e[0] == 'sleep']
        self.assertEqual(sleeps, [5] + [3] * 3 + [5] + [3] * 17 + [10])
        actions = [e for e in events if e[0] != 'state']
        self.assertEqual(actions[:3], [('invoke', (9609,)), ('sleep', 5), ('invoke', (9601, {'0': 2, '1': 83}))])

    async def test_membership_failure_never_removes(self):
        refresh, events = await self.client([{}], images=[{'imageIndex': 100}])
        with self.assertRaisesRegex(FrameError, 'cloud album'):
            await refresh()
        self.assertEqual(events, [])

    async def test_release_timeout_never_downloads_or_selects(self):
        for state in ({'9606': {'value': [83, 100]}},):
            with self.subTest(state=state):
                refresh, events = await self.client([state])
                with self.assertRaisesRegex(FrameError, 'releasing'):
                    await refresh()
                self.assertEqual([e[1] for e in events if e[0] == 'invoke'], [(9609,), (9601, {'0': 2, '1': 83})])
                self.assertEqual(sum(e[0] == 'state' for e in events), 31)

    async def test_unknown_initial_storage_never_removes(self):
        refresh, events = await self.client([{'9606': {'value': None}}])
        with self.assertRaisesRegex(FrameError, 'Cannot verify device storage'):
            await refresh()
        self.assertFalse(any(e[0] == 'invoke' for e in events))

    async def test_presence_timeout_never_selects(self):
        refresh, events = await self.client([{'9606': {'value': [100]}}])
        with self.assertRaisesRegex(FrameError, 'storing'):
            await refresh()
        self.assertFalse(any(e[0] == 'invoke' and e[1][0] == 9602 for e in events))

    async def test_download_retry_wakes_again_without_releasing_twice(self):
        absent = {'9606': {'value': [100]}}
        present = {'9606': {'value': [100, 83]}}
        refresh, events = await self.client([absent] * 41 + [present])
        await refresh()
        commands = [e[1] for e in events if e[0] == 'invoke']
        self.assertEqual(commands, [(9609,), (9601, {'0': 1, '1': 83}),
                                    (9609,), (9601, {'0': 1, '1': 83}),
                                    (9602, {'0': 83})])

    async def test_download_retry_is_bounded_to_two_requests(self):
        refresh, events = await self.client([{'9606': {'value': [100]}}])
        with self.assertRaisesRegex(FrameError, 'two bounded download attempts'):
            await refresh()
        commands = [e[1] for e in events if e[0] == 'invoke']
        self.assertEqual(commands.count((9601, {'0': 1, '1': 83})), 2)
        self.assertFalse(any(command[0] == 9602 for command in commands))

    async def test_new_upload_selection_does_not_refresh_again(self):
        client = NS(reported_state=AsyncMock(return_value={'9606': {'value': [83]}}),
                    show=AsyncMock(), refresh_image=AsyncMock())
        select = method('switchbot_frame_control/protocol.py', 'select_downloaded')
        self.assertTrue(await select(client, 83, 'frame1'))
        client.show.assert_awaited_once_with(83, 'frame1')
        client.refresh_image.assert_not_awaited()

    def reminder(self):
        snapshot = {'index': 100, 'test': True}
        client = NS(refresh_image=AsyncMock(),
                    reported_state=AsyncMock(return_value={'9601': {'value': 83}}), show=AsyncMock(),
                    catalogue=AsyncMock(return_value=[{'imageIndex': 83}, {'imageIndex': 100}]),
                    invoke=AsyncMock())
        obj = NS(lock=asyncio.Lock(), data={'snapshot': snapshot, 'slot_kind': 'blue',
                                         'artwork_revision': '{}', 'slot': {'index': 83}},
                 config={}, manager=NS(lock=asyncio.Lock(), client=client, data={},
                            config={'model': 'frame1', 'panel_size': '31.5'}, connection_mode=lambda: 'wifi'),
                 save=AsyncMock(), publish=Mock(), put_assets=AsyncMock(), record_refresh=AsyncMock(),
                 wait_released=AsyncMock(return_value={'9601': {'value': 100}, '9606': {'value': [100]}}),
                 provision=AsyncMock(return_value={'index': 83, 'names': ['synthetic-main', 'synthetic-thumb', 'synthetic-bin']}))
        return obj, snapshot

    async def test_same_kind_always_refreshes_without_upload(self):
        obj, snapshot = self.reminder()
        show = method('frame_bin_reminder/__init__.py', 'show',
                      dt_util=NS(now=lambda: datetime.now(timezone.utc)))
        await show(obj, kind='blue', test=True)
        obj.put_assets.assert_not_awaited()
        obj.manager.client.refresh_image.assert_awaited_once_with(83, trace=obj.record_refresh)
        self.assertIs(obj.data['snapshot'], snapshot)

    async def test_refresh_timeout_preserves_snapshot_and_revision(self):
        obj, snapshot = self.reminder()
        obj.manager.client.refresh_image.side_effect = FrameError('releasing timed out')
        show = method('frame_bin_reminder/__init__.py', 'show',
                      dt_util=NS(now=lambda: datetime.now(timezone.utc)))
        with self.assertRaises(FrameError):
            await show(obj, kind='blue', test=True)
        self.assertIs(obj.data['snapshot'], snapshot)
        obj.save.assert_not_awaited()
        self.assertFalse(any(call.args == ('display_requested',) for call in obj.publish.call_args_list))

    async def test_restore_uses_refresh_and_only_clears_confirmed_snapshot(self):
        obj, _ = self.reminder()
        obj.manager.client.reported_state.side_effect = [
            {'9601': {'value': 83}, '9606': {'value': [83, 100]}},
            {'9601': {'value': 100}, '9606': {'value': [83, 100]}},
        ]
        restore = method('frame_bin_reminder/__init__.py', 'restore')
        await restore(obj)
        obj.manager.client.refresh_image.assert_awaited_once_with(100, trace=obj.record_refresh)
        self.assertNotIn('snapshot', obj.data)

    async def test_restore_failure_retains_snapshot(self):
        obj, snapshot = self.reminder()
        obj.manager.client.refresh_image.side_effect = FrameError('not in cloud album')
        restore = method('frame_bin_reminder/__init__.py', 'restore')
        with self.assertRaises(FrameError):
            await restore(obj)
        self.assertIs(obj.data['snapshot'], snapshot)

    async def test_wifi_frame1_refresh_frame2_unchanged(self):
        select = method('switchbot_frame_control/__init__.py', 'select_image')
        for model in ('frame1', 'frame2'):
            client = NS(refresh_image=AsyncMock(), show=AsyncMock())
            obj = NS(check_index=lambda i: i, lock=asyncio.Lock(), connection_mode=lambda: 'wifi',
                     config={'model': model}, client=client, publish=Mock())
            await select(obj, 83)
            if model == 'frame1':
                client.refresh_image.assert_awaited_once_with(83)
                client.show.assert_not_awaited()
            else:
                client.refresh_image.assert_not_awaited()
                client.show.assert_awaited_once_with(83, 'frame2')

    async def test_ble_does_not_refresh_cloud_copy(self):
        frame = NS(indices=AsyncMock(return_value=[83]), show=AsyncMock(), mode_info=AsyncMock(return_value={}))

        class Context:
            async def __aenter__(self):
                return frame

            async def __aexit__(self, *args):
                return False

        client = NS(refresh_image=AsyncMock(), show=AsyncMock())
        obj = NS(check_index=lambda i: i, lock=asyncio.Lock(), connection_mode=lambda: 'local',
                 config={'model': 'frame1'}, client=client, publish=Mock(),
                 local_connection=AsyncMock(return_value=Context()), mode_matches=lambda *args: True)
        select = method('switchbot_frame_control/__init__.py', 'select_image')
        await select(obj, 83)
        frame.show.assert_awaited_once_with(83)
        client.refresh_image.assert_not_awaited()
        client.show.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
