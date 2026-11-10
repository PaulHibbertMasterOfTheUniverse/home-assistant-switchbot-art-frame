"""Resume restoration from synthetic delayed shadows without repeating mutations."""
import asyncio
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import test_frame_bin_cleanup_manual as previous
from test_frame_cache_refresh import FrameError, method


class IdempotentRestoreTests(previous.CleanupManualTests):
    async def test_original_selected_skips_refresh_but_purges_notification(self):
        obj, _ = self.reminder()
        obj.manager.client.reported_state.return_value = {'9601': {'value': 100}, '9606': {'value': [100, 83]}}
        await method('frame_bin_reminder/__init__.py', 'restore')(obj)
        obj.manager.client.refresh_image.assert_not_awaited()
        self.assertEqual(obj.manager.client.invoke.await_args_list[-1].args, (9601, {'0': 2, '1': 83}))
        self.assertNotIn('snapshot', obj.data)

    async def test_already_absent_no_redownload_no_delete_records_evidence(self):
        obj, _ = self.reminder()
        obj.manager.client.reported_state.return_value = {'9601': {'value': 100}, '9606': {'value': [100]}}
        await method('frame_bin_reminder/__init__.py', 'restore')(obj)
        obj.manager.client.refresh_image.assert_not_awaited()
        obj.manager.client.invoke.assert_not_awaited()
        obj.wait_released.assert_not_awaited()
        self.assertNotIn('snapshot', obj.data)
        self.assertEqual(obj.data['cleanup_verification']['selected_index'], 100)
        self.assertTrue(obj.data['cleanup_verification']['notification_cloud_retained'])

    async def test_resume_after_selection_timeout_preserves_original_deadline(self):
        obj, snapshot = self.reminder()
        snapshot['deadline'] = '2026-11-10T19:30:00+00:00'
        obj.manager.client.reported_state.return_value = {'9601': {'value': 0}, '9606': {'value': [100, 83]}}
        restore = method('frame_bin_reminder/__init__.py', 'restore')
        with self.assertRaisesRegex(FrameError, 'selection not yet confirmed'):
            await restore(obj)
        self.assertIs(obj.data['snapshot'], snapshot)
        self.assertEqual(snapshot['deadline'], '2026-11-10T19:30:00+00:00')
        self.assertTrue(snapshot['restore_requested'])
        obj.manager.client.invoke.assert_not_awaited()
        obj.manager.client.refresh_image.assert_awaited_once_with(100, trace=obj.record_refresh)
        obj.manager.client.refresh_image.reset_mock()
        obj.manager.client.reported_state.return_value = {'9601': {'value': 100}, '9606': {'value': [100]}}
        await restore(obj)
        obj.manager.client.refresh_image.assert_not_awaited()
        obj.manager.client.invoke.assert_not_awaited()
        self.assertNotIn('snapshot', obj.data)

    async def test_delayed_selection_beyond_ten_polls_succeeds(self):
        obj, _ = self.reminder()
        stale = {'9601': {'value': 0}, '9606': {'value': [100, 83]}}
        selected = {'9601': {'value': 100}, '9606': {'value': [100, 83]}}
        obj.manager.client.reported_state.side_effect = [stale] * 21 + [selected]
        await method('frame_bin_reminder/__init__.py', 'restore')(obj)
        self.assertNotIn('snapshot', obj.data)

    async def test_unknown_storage_cannot_count_as_finished_cleanup(self):
        obj, snapshot = self.reminder()
        obj.manager.client.reported_state.return_value = {'9601': {'value': 100}, '9606': {'value': None}}
        with self.assertRaisesRegex(FrameError, 'selection not yet confirmed'):
            await method('frame_bin_reminder/__init__.py', 'restore')(obj)
        self.assertIs(obj.data['snapshot'], snapshot)
        obj.manager.client.invoke.assert_not_awaited()

    async def test_next_minute_retries_before_future_deadline(self):
        obj, snapshot = self.reminder()
        snapshot.update(deadline='2026-11-10T19:30:00+00:00', restore_requested=True)
        obj.run = AsyncMock()
        tick = method('frame_bin_reminder/__init__.py', 'tick',
                      dt_util=NS(parse_datetime=datetime.fromisoformat))
        await tick(obj, datetime(2026, 11, 9, 16, tzinfo=timezone.utc))
        obj.run.assert_awaited_once_with('restore')

    async def test_minute_does_not_queue_duplicate_while_locked(self):
        obj, snapshot = self.reminder()
        snapshot.update(deadline='2026-11-10T19:30:00+00:00', restore_requested=True)
        obj.run = AsyncMock()
        tick = method('frame_bin_reminder/__init__.py', 'tick')
        async with obj.lock:
            await tick(obj, datetime(2026, 11, 9, 16, tzinfo=timezone.utc))
        obj.run.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
