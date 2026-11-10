"""Synthetic tests for manual deadlines and device-only notification cleanup."""
import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch
import test_frame_cache_refresh as cache
from test_frame_cache_refresh import FrameError, method


class CleanupManualTests(cache.RefreshTests):
    async def test_run_preserves_known_safe_frame_error(self):
        message = 'Frame has not confirmed releasing the picture; download not attempted'
        obj = NS(fail=AsyncMock(side_effect=FrameError(message)), publish=Mock(), hass=NS())
        notification = NS(async_create=Mock())
        with patch.dict(sys.modules, {'homeassistant.components.persistent_notification': notification}):
            with self.assertRaisesRegex(FrameError, 'releasing the picture'):
                await method('frame_bin_reminder/__init__.py', 'run', DOMAIN='frame_bin_reminder')(obj, 'fail')
        obj.publish.assert_called_once_with('error', message)

    async def test_run_hides_unknown_exception_details(self):
        obj = NS(fail=AsyncMock(side_effect=RuntimeError('private synthetic detail')), publish=Mock(), hass=NS())
        notification = NS(async_create=Mock())
        with patch.dict(sys.modules, {'homeassistant.components.persistent_notification': notification}):
            with self.assertRaisesRegex(FrameError, '^RuntimeError$'):
                await method('frame_bin_reminder/__init__.py', 'run', DOMAIN='frame_bin_reminder')(obj, 'fail')
        obj.publish.assert_called_once_with('error', 'RuntimeError')

    async def test_exact_cleanup_precedes_snapshot_clear(self):
        obj, snapshot = self.reminder()
        obj.manager.client.reported_state.side_effect = [
            {'9601': {'value': 83}, '9606': {'value': [83, 100]}},
            {'9601': {'value': 100}, '9606': {'value': [83, 100]}},
        ]
        order = []

        async def refresh(index, **kwargs):
            order.append(('refresh', index))
            self.assertIs(obj.data['snapshot'], snapshot)

        async def invoke(function, params=None):
            order.append(('invoke', function) if params is None else ('invoke', function, params))
            self.assertIs(obj.data['snapshot'], snapshot)

        async def released(index):
            order.append(('released', index))
            self.assertIs(obj.data['snapshot'], snapshot)
            return {'9601': {'value': 100}, '9606': {'value': [100]}}

        async def sleep(seconds):
            order.append(('sleep', seconds))

        obj.manager.client.refresh_image.side_effect = refresh
        obj.manager.client.invoke.side_effect = invoke
        obj.wait_released.side_effect = released
        await method('frame_bin_reminder/__init__.py', 'restore', asyncio=NS(sleep=sleep))(obj)
        self.assertEqual(order, [('refresh', 100), ('invoke', 9609), ('sleep', 5),
                                 ('invoke', 9601, {'0': 2, '1': 83}), ('released', 83)])
        self.assertNotIn('snapshot', obj.data)
        self.assertTrue(obj.data['cleanup_verification']['notification_cloud_retained'])

    async def test_purge_timeout_preserves_snapshot(self):
        obj, snapshot = self.reminder()
        obj.manager.client.reported_state.return_value = {'9601': {'value': 100}, '9606': {'value': [83, 100]}}
        obj.wait_released.side_effect = FrameError('purge timeout')
        with self.assertRaisesRegex(FrameError, 'purge timeout'):
            await method('frame_bin_reminder/__init__.py', 'restore')(obj)
        self.assertIs(obj.data['snapshot'], snapshot)
        obj.save.assert_awaited_once()
        self.assertTrue(snapshot['restore_requested'])

    async def test_notification_original_guard_before_any_refresh(self):
        obj, snapshot = self.reminder()
        obj.data['slot']['index'] = 100
        with self.assertRaisesRegex(FrameError, 'separate notification'):
            await method('frame_bin_reminder/__init__.py', 'restore')(obj)
        obj.manager.client.refresh_image.assert_not_awaited()
        obj.manager.client.invoke.assert_not_awaited()
        self.assertIs(obj.data['snapshot'], snapshot)

    async def test_cloud_original_missing_blocks_refresh(self):
        obj, snapshot = self.reminder()
        obj.manager.client.catalogue.return_value = [{'imageIndex': 83}]
        with self.assertRaisesRegex(FrameError, 'cloud album'):
            await method('frame_bin_reminder/__init__.py', 'restore')(obj)
        obj.manager.client.refresh_image.assert_not_awaited()
        self.assertIs(obj.data['snapshot'], snapshot)

    async def test_cloud_membership_allows_original_absent_locally(self):
        obj, _ = self.reminder()
        obj.manager.client.reported_state.side_effect = [
            {'9601': {'value': 0}, '9606': {'value': [83]}},
            {'9601': {'value': 100}, '9606': {'value': [83, 100]}},
        ]
        await method('frame_bin_reminder/__init__.py', 'restore')(obj)
        obj.manager.client.refresh_image.assert_awaited_once_with(100, trace=obj.record_refresh)
        self.assertNotIn('snapshot', obj.data)

    async def manual(self, now, *, explicit=100, current=83, stored=None, test=False):
        obj, _ = self.reminder()
        obj.data.pop('snapshot')
        obj.manager.client.reported_state.side_effect = [
            {'9601': {'value': current}, '9606': {'value': [83, 100] if stored is None else stored}},
            {'9601': {'value': 83}},
        ]
        show = method('frame_bin_reminder/__init__.py', 'show', dt_util=NS(now=lambda: now))
        await show(obj, kind='black', manual=not test, test=test, restore_index=explicit)
        return obj

    async def test_manual_monday_deadline_next_tuesday(self):
        now = datetime(2026, 11, 9, 15, tzinfo=timezone.utc)
        obj = await self.manual(now)
        self.assertEqual(obj.data['snapshot']['deadline'], '2026-11-10T19:30:00+00:00')
        self.assertEqual(obj.data['snapshot']['index'], 100)
        self.assertNotIn('last_display_window', obj.data)

    async def test_manual_tuesday_after_cleanup_deadline_next_week(self):
        obj = await self.manual(datetime(2026, 11, 10, 20, tzinfo=timezone.utc))
        self.assertEqual(obj.data['snapshot']['deadline'], '2026-11-17T19:30:00+00:00')

    async def test_manual_tuesday_before_cleanup_same_day(self):
        obj = await self.manual(datetime(2026, 11, 10, 18, tzinfo=timezone.utc))
        self.assertEqual(obj.data['snapshot']['deadline'], '2026-11-10T19:30:00+00:00')

    async def test_manual_without_explicit_original_rejects_current_slot(self):
        with self.assertRaisesRegex(FrameError, 'no saved original'):
            await self.manual(datetime(2026, 11, 9, tzinfo=timezone.utc), explicit=None)

    async def test_manual_rejects_nonstored_or_notification_original(self):
        for explicit in (83, 99):
            with self.subTest(explicit=explicit), self.assertRaisesRegex(FrameError, 'different from'):
                await self.manual(datetime(2026, 11, 9, tzinfo=timezone.utc), explicit=explicit)

    async def test_existing_snapshot_and_window_preserved(self):
        obj, snapshot = self.reminder()
        obj.data['last_display_window'] = 'old-window'
        await method('frame_bin_reminder/__init__.py', 'show')(obj, kind='black', manual=True, restore_index=99)
        self.assertIs(obj.data['snapshot'], snapshot)
        self.assertEqual(obj.data['last_display_window'], 'old-window')

    async def test_ten_minute_test_deadline_unchanged(self):
        now = datetime(2026, 11, 9, 15, tzinfo=timezone.utc)
        obj = await self.manual(now, explicit=None, current=100, test=True)
        self.assertEqual(obj.data['snapshot']['deadline'], (now+timedelta(minutes=10)).isoformat())

    async def test_wait_release_unknown_never_counts_as_absent(self):
        obj, _ = self.reminder()
        obj.manager.client.reported_state.return_value = {'9606': {'value': None}}
        sleep = AsyncMock()
        wait = method('frame_bin_reminder/__init__.py', 'wait_released', asyncio=NS(sleep=sleep))
        with self.assertRaisesRegex(FrameError, 'still stored'):
            await wait(obj, 83)
        self.assertEqual(sleep.await_count, 30)


if __name__ == '__main__':
    unittest.main()
