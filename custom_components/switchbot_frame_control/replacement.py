"""Bounded, restart-resumable replacement of exactly one confirmed artwork.

Manager's lock owns every call. No startup task removes artwork: after a bounded
timeout, the same source must be submitted again to resume the saved transaction.
Only slot identity, source digest and backup metadata are persisted, not images.
"""
import asyncio
import time
from urllib.parse import urlparse

from .protocol import FrameError


class Replacement:
    def __init__(self, manager):
        self.manager = manager

    @property
    def pending(self):
        return self.manager.data.get('pending_replacement')

    async def note(self, stage, **details):
        pending = self.pending
        pending['stage'] = stage
        pending['updated_at'] = time.time()
        pending.setdefault('events', []).append({'at': pending['updated_at'], 'stage': stage, **details})
        pending['events'] = pending['events'][-24:]
        await self.manager.save_verified()
        self.manager.last_action = 'Recovering confirmed replacement; ' + stage.replace('_', ' ')
        self.manager.publish('replacing_oldest')

    async def snapshot(self):
        manager = self.manager
        state = await manager.client.reported_state()
        values = state.get('9606', {}).get('value')
        if not isinstance(values, list) or any(type(i) is not int or not 0 <= i <= 255 for i in values):
            raise FrameError('Cannot verify device capacity; replacement remains pending')
        items = await manager.client.catalogue()
        if not isinstance(items, list) or any(not isinstance(i, dict) or type(i.get('imageIndex')) is not int
                                            or not 1 <= i['imageIndex'] <= 255 for i in items):
            raise FrameError('Cannot verify cloud capacity; replacement remains pending')
        if len({i['imageIndex'] for i in items}) != len(items):
            raise FrameError('Cloud catalogue has duplicate indices; replacement remains pending')
        return set(values) - {0}, {i['imageIndex']: i for i in items}

    async def verify(self, stored, items):
        pending = self.pending
        index = pending['index']
        if index in self.manager.protected_indices():
            raise FrameError('Replacement slot is now protected; nothing else was removed')
        if index in items and self.identity(items[index]) != pending['identity']:
            raise FrameError('Replacement slot identity changed; refusing to remove reused artwork')
        if not set(pending['other_stored']).issubset(stored) or not set(pending['other_cloud']).issubset(items):
            raise FrameError('Other artwork membership changed; replacement paused for review')
        await self.manager.verify_replacement_backup(pending['backup'])

    @staticmethod
    def identity(item):
        # Never persist signed URLs. Creation time + vendor ID + object basename
        # detect a slot reused for another artwork before retrying any deletion.
        return [str(item.get('createdAt')), str(item.get('imageUniqueId', '')),
                urlparse(item.get('mainImageUrl', '')).path.rsplit('/', 1)[-1]]

    def ready(self, stored, items):
        pending = self.pending
        return (pending['index'] not in stored and len(stored) < 10 and len(items) < 10
                and (not pending['remove_cloud'] or pending['index'] not in items))

    async def check_ready(self, digest):
        if not self.pending:
            return
        if digest != self.pending['sha256']:
            raise FrameError('Resume the pending replacement with the same picture; no other artwork was removed')
        stored, items = await self.snapshot()
        await self.verify(stored, items)
        if not self.ready(stored, items):
            raise FrameError('Device and cloud capacity are not both confirmed safe; no new picture was registered')
        index = self.pending['index']
        self.manager.data['normal_indices'] = [i for i in self.manager.data['normal_indices'] if i != index]
        if self.pending['remove_cloud']:
            ledger = self.manager.data.get('cloud_art_uploads', {})
            for key in [key for key, value in ledger.items() if value == index]:
                del ledger[key]
        await self.note('capacity_confirmed', stored_indices=sorted(stored), cloud_indices=sorted(items))

    async def complete(self, digest, new_index):
        if self.pending and self.pending['sha256'] == digest:
            result = dict(self.pending)
            result.update(stage='registered', new_index=new_index, completed_at=time.time())
            self.manager.data['last_replacement'] = result
            self.manager.data.pop('pending_replacement')
            await self.manager.save_verified()

    async def prepare(self, index, digest):
        manager = self.manager
        index = manager.check_index(index)
        if manager.data.get('pending_cloud_registration'):
            raise FrameError('Reconcile the uncertain registration before resuming replacement; nothing was removed')
        previous = manager.data.get('last_replacement', {})
        if (not self.pending and previous.get('index') == index and previous.get('sha256') == digest
                and digest in manager.data.get('cloud_art_uploads', {})):
            return  # A repeated HTTP request must reuse the registered entry.
        if self.pending:
            if self.pending['index'] != index or self.pending['sha256'] != digest:
                raise FrameError('A different replacement is pending; no second artwork was removed')
            if digest in manager.data.get('cloud_art_uploads', {}):
                await self.complete(digest, manager.data['cloud_art_uploads'][digest])
                return
        else:
            candidate = await manager.oldest_stored(await manager.client.reported_state())
            if candidate is None:
                return  # Capacity was freed before confirmation; do not delete.
            if candidate['index'] != index:
                raise FrameError('The oldest stored picture changed; review a new confirmation before removing anything')
            stored, items = await self.snapshot()
            if index not in stored or index not in items or str(items[index].get('createdAt')) != str(candidate['created_at']):
                raise FrameError('Replacement identity changed before backup; nothing was removed')
            await manager.archive_cloud_art(index, list(items.values()))
            backup = dict(manager.data['last_archived_art'])
            if backup.get('index') != index:
                raise FrameError('Replacement backup belongs to another artwork; nothing was removed')
            await manager.verify_replacement_backup(backup)
            manager.data['pending_replacement'] = {
                'index': index, 'created_at': candidate['created_at'], 'sha256': digest,
                'identity': self.identity(items[index]),
                'backup': backup, 'remove_cloud': len(items) >= 10,
                'other_stored': sorted(stored - {index}), 'other_cloud': sorted(set(items) - {index}),
                'release_requests': 0, 'cloud_delete_requests': 0, 'cloud_sync_requests': 0,
                'started_at': time.time(),
            }
            await self.note('backup_verified')  # Durable intent precedes mutation.

        # Two 120-second observation windows, each with wake + five seconds.
        # Command budgets live in Store and are NOT reset on timeout/restart.
        for window in range(2):
            stored, items = await self.snapshot()
            await self.verify(stored, items)
            if self.ready(stored, items):
                await self.check_ready(digest)
                return
            await self.note('wake_before_release', window=window + 1)
            try:
                await manager.client.invoke(9609)
                await asyncio.sleep(5)
                stored, items = await self.snapshot()
                await self.verify(stored, items)
                if index in stored and self.pending['release_requests'] < 2:
                    self.pending['release_requests'] += 1
                    await self.note('device_release', index=index)
                    await manager.client.invoke(9601, {'0': 2, '1': index})
                if self.pending['remove_cloud']:
                    # Recheck identity before EACH cloud mutation. A lost reply
                    # may already have removed the item; never choose a new one.
                    for counter, endpoint, key in (
                        ('cloud_delete_requests', '/device/artframe/api/v1/images/delete', 'imageIndexList'),
                        ('cloud_sync_requests', '/productbiz/v1/slideshow/syncDeletedImages', 'imageIndexes'),
                    ):
                        stored, items = await self.snapshot()
                        await self.verify(stored, items)
                        needed = index in items if counter == 'cloud_delete_requests' else not self.pending.get(counter + '_confirmed')
                        if needed and self.pending[counter] < 2:
                            self.pending[counter] += 1
                            await self.note(counter, index=index)
                            await manager.client.post(endpoint, {'deviceID': manager.client.device,
                                'groupID': manager.client.group, key: [index], 'deleteAll': False})
                            self.pending[counter + '_confirmed'] = True
                            await self.note(counter + '_accepted', index=index)
            except (FrameError, asyncio.TimeoutError) as error:
                # Uncertain command reply: observe first, never broaden deletion.
                await self.note('command_reply_uncertain', error_type=type(error).__name__)
            for poll in range(41):
                stored, items = await self.snapshot()
                await self.verify(stored, items)
                if self.ready(stored, items):
                    manager.data['normal_indices'] = [i for i in manager.data['normal_indices'] if i != index]
                    manager.data['last_replaced_image'] = {'index': index, 'created_at': self.pending['created_at']}
                    await self.check_ready(digest)
                    return
                if poll < 40:
                    await asyncio.sleep(3)
        await self.note('capacity_timeout', stored_indices=sorted(stored), cloud_indices=sorted(items))
        raise FrameError('Replacement remains pending after two bounded capacity waits; backup retained. '
                         'Send the same picture again to resume; no new picture was registered')
