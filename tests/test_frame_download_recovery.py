"""Synthetic upload-target, persisted-trace and bounded-recovery regressions."""
import hashlib
import json
import re
import unittest
from pathlib import Path
from urllib.parse import urlparse
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
import test_frame_idempotent_restore as previous
from test_frame_cache_refresh import method


class RecoveryTests(previous.IdempotentRestoreTests):
    async def test_upload_matches_confirmed_mac_filename_type_headers_and_length(self):
        names = ['main_'+'0'*32+'.jpg', 'thumbnail_'+'0'*32+'.jpg', 'bin_'+'0'*32+'.bin']
        assets = [b'synthetic jpeg', b'synthetic thumbnail', bytes(1843200)]

        class Response:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        client = NS(device='synthetic-device', group='synthetic-group',
                    post=AsyncMock(return_value={'uploadUrl': 'https://synthetic.s3.amazonaws.com/asset'}))
        obj = NS(read_artwork=Mock(return_value=assets), data={}, config={'artwork_directory': 'synthetic'},
                 manager=NS(client=client), save=AsyncMock(),
                 hass=NS(config=NS(path=lambda _: '/synthetic'), async_add_executor_job=AsyncMock(return_value=assets)),
                 http=NS(put=Mock(side_effect=lambda *args, **kwargs: Response())))
        upload = method('frame_bin_reminder/__init__.py', 'put_assets',
                        Path=Path, re=re, hashlib=hashlib, urlparse=urlparse)
        await upload(obj, names, 'black')
        self.assertEqual([call.args[1]['fileType'] for call in client.post.await_args_list], [1, 2, 3])
        self.assertEqual(client.post.await_args_list[-1].args[1]['filename'], names[2])
        request = obj.http.put.call_args_list[-1]
        self.assertEqual(len(request.kwargs['data']), 1843200)
        self.assertEqual(request.kwargs['headers'], {'Content-Type': 'text/plain'})
        self.assertEqual([row['http_status'] for row in obj.data['asset_uploads']], [200, 200, 200])

    async def test_forced_reupload_uses_existing_slot_without_registration(self):
        obj, snapshot = self.reminder()
        obj.data['slot_kind'] = 'black'
        await method('frame_bin_reminder/__init__.py', 'show')(obj, kind='black', manual=True, force_upload=True)
        obj.put_assets.assert_awaited_once()
        obj.manager.client.refresh_image.assert_awaited_once_with(83, trace=obj.record_refresh)
        self.assertIs(obj.data['snapshot'], snapshot)

    async def test_trace_is_deep_copied_and_saved(self):
        obj, _ = self.reminder()
        details = {'index': 83, 'events': [{'at': 1, 'stage': 'download_request'}]}
        await method('frame_bin_reminder/__init__.py', 'record_refresh', json=json)(obj, details)
        details['events'].append({'at': 2, 'stage': 'later'})
        self.assertEqual(len(obj.data['last_refresh']['events']), 1)
        obj.save.assert_awaited_once()

    async def test_stage_trace_proves_presence_before_selection(self):
        refresh, _ = await self.client([{'9606': {'value': [100]}}, {'9606': {'value': [100, 83]}}])
        snapshots = []

        async def record(details):
            snapshots.append(json.loads(json.dumps(details)))

        await refresh(trace=record)
        stages = [row['stage'] for row in snapshots]
        self.assertIn('already_absent_release_skipped', stages)
        self.assertLess(stages.index('storage_confirmed'), stages.index('selection_request'))
        self.assertTrue(all('at' in event for event in snapshots[-1]['events']))


if __name__ == '__main__':
    unittest.main()
