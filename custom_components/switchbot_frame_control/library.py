"""Upload first; durable identity-bound cleanup never reserves spare capacity.

Entry points and individual cleanup steps hold Manager.lock. Polling waits do
not. Cleanup intents survive subsequent deliveries, failures and restarts.
"""
import asyncio
import copy
import hashlib
import json
from urllib.parse import urlparse

from .protocol import FrameError


class Library:
    def __init__(self, manager):
        self.m = manager

    def supported(self):
        if (self.m.config.get('model') != 'frame1' or self.m.config.get('panel_size') != '31.5'
                or self.m.connection_mode() != 'wifi'):
            raise FrameError('Upload-first library mode supports original 31.5-inch frames in Wi-Fi mode')

    def enabled(self):
        return bool(self.m.data.get('library_mode'))

    @property
    def gallery(self):
        gallery = self.m.hass.data.get('frame_art_gallery')
        if gallery is None:
            raise FrameError('Private HA gallery is not available; nothing was removed')
        return gallery

    def protected(self):
        # Preserve the entire existing normal-restore set, not just notifications.
        # No migration/re-upload of those references is attempted by this pilot.
        result = (set(self.m.protected_indices()) | set(self.m.data['normal_indices'])
                  | set(self.m.data.get('library_retained_indices', [])))
        reminder = self.m.hass.data.get('frame_bin_reminder')
        if reminder is not None and getattr(reminder, 'manager', None) is self.m:
            for value in (reminder.data.get('slot', {}).get('index'),
                          reminder.data.get('snapshot', {}).get('index')):
                if type(value) is int:
                    result.add(value)
        return result

    def restoration_active(self):
        reminder = self.m.hass.data.get('frame_bin_reminder')
        return bool(self.m.desired() or (reminder is not None
            and getattr(reminder, 'manager', None) is self.m and reminder.data.get('snapshot')))

    @staticmethod
    def identity(item):
        return [str(item.get('createdAt')), str(item.get('imageUniqueId', '')),
                str(item.get('id', '')), urlparse(item.get('mainImageUrl', '')).path]

    async def snapshot(self):
        self.supported()
        state = await self.m.client.reported_state()
        values = state.get('9606', {}).get('value')
        selected = state.get('9601', {}).get('value')
        mode = state.get('9603', {}).get('value')
        rows = await self.m.client.catalogue()
        if (not isinstance(values, list) or any(type(i) is not int or not 0 <= i <= 255 for i in values)
                or type(selected) is not int or not 1 <= selected <= 255 or mode != 0
                or not isinstance(rows, list) or any(not isinstance(i, dict)
                    or type(i.get('imageIndex')) is not int or not 1 <= i['imageIndex'] <= 255 for i in rows)):
            raise FrameError('Cannot verify current frame/catalogue snapshot; nothing was removed')
        items = {i['imageIndex']: i for i in rows}
        if len(items) != len(rows):
            raise FrameError('Duplicate cloud slots; library operation paused')
        return selected, set(values) - {0}, items

    def unsettled(self,items):
        # The meaning of vendor status=0 is not assumed from storage alone.
        reconciled=self.m.data.get('library_reconciled_status',{})
        return [i for i, row in items.items() if (type(row.get('status')) is not int or row['status'] != 1)
                and not (row.get('status')==0 and reconciled.get(str(i))==self.identity(row))]

    async def inspect(self):
        selected, stored, items = await self.snapshot()
        transaction = self.m.data.get('library_transaction', {})
        return {'selected_index': selected, 'stored_indices': sorted(stored),
                'cloud': [{'index': i, 'status': row.get('status')} for i, row in sorted(items.items())],
                'unsettled_cloud_indices': self.unsettled(items),
                'protected_indices': sorted(self.protected()),
                'restoration_active': self.restoration_active(),
                'pending_registration': bool(self.m.data.get('pending_cloud_registration')),
                'pending_replacement': bool(self.m.data.get('pending_replacement')),
                'library_mode': self.enabled(),
                'manager_busy': False,
                'cleanup_pending': self.cleanup_pending(),
                'spare_capacity': max(0, min(10-len(stored), 10-len(items))),
                'transaction': self.describe(transaction),
                'cleanup_queue': [{**self.describe(t),
                    'previous_stored': (t.get('previous') or {}).get('index') in stored,
                    'previous_cloud_identity_matches': (
                        self.identity(items[(t.get('previous') or {}).get('index')]) == t['previous']['identity']
                        if (t.get('previous') or {}).get('index') in items else None)}
                    for t in self.m.data.get('library_cleanup_queue', [])],
                'device_cleanup': self.m.data.get('library_device_cleanup'),
                'transaction_stage': self.m.data.get('library_transaction', {}).get('stage')}

    async def archive(self, index, item, raw=None, known_layout=False):
        if raw is None:
            raw = await self.m.read_image(item['mainImageUrl'])
        metadata = {key: item[key] for key in ('imageIndex', 'id', 'imageUniqueId', 'createdAt',
                    'angle', 'status', 'fileTitle', 'fileDesc') if key in item}
        metadata['identity'] = self.identity(item)
        async with self.gallery.lock:
            image_id = await self.m.hass.async_add_executor_job(self.gallery.import_transport,
                raw, self.m.frame_id, dict(self.m.data['layout']), self.m.config['panel_size'],
                metadata, known_layout)
            await self.m.hass.async_add_executor_job(self.gallery.verify_transport, image_id)
        return image_id

    async def verify(self, image_id):
        return await self.m.hass.async_add_executor_job(self.gallery.verify_transport, image_id)

    async def backup_all(self):
        """Only GETs plus private local imports. Never frees a slot or selects."""
        selected, stored, items = await self.snapshot()
        backups = {}
        for index, item in sorted(items.items()):
            backups[str(index)] = {'identity': self.identity(item), 'gallery_id': await self.archive(index, item)}
        for index in sorted(stored-set(items)):
            image_id = await self.m.hass.async_add_executor_job(self.gallery.migration_backup,index)
            backups[str(index)] = {'identity': None, 'gallery_id': image_id, 'stored_only': True}
        selected2, stored2, items2 = await self.snapshot()
        if (selected2 != selected or stored2 != stored or set(items2) != set(items)
                or any(self.identity(items2[i]) != self.identity(row) for i, row in items.items())):
            raise FrameError('Snapshot changed or stored-only artwork lacks a cloud source; partial imports retained, backup not complete')
        report = {'complete': True, 'selected_index': selected, 'stored_indices': sorted(stored),
                  'backups': backups, 'unsettled_cloud_indices': self.unsettled(items2),
                  'protected_indices': sorted(self.protected()), 'cleanup_performed': False}
        self.m.data['library_backup'] = report
        await self.m.save_verified()
        return report

    async def set_enabled(self, enabled, retain_indices, recover_index=None):
        self.supported()
        if enabled:
            if self.restoration_active() or self.m.data.get('pending_cloud_registration') or self.m.data.get('pending_replacement'):
                raise FrameError('Resolve notification/transfer intent before enabling library mode')
            report = await self.backup_all()
            selected,stored,items=await self.snapshot()
            # Some legacy catalogue entries remain status=0 after device delivery.
            # Reconcile only fresh stored selection / explicitly retained return
            # targets with matching verified originals, not arbitrary album rows.
            for index in ({selected}|set(retain_indices))&stored&set(items):
                backup=report['backups'].get(str(index),{})
                if items[index].get('status')==0 and backup.get('identity')==self.identity(items[index]):
                    self.m.data.setdefault('library_reconciled_status',{})[str(index)]=self.identity(items[index])
            unsettled = set(self.unsettled(items))
            if unsettled - ({recover_index} if recover_index is not None else set()):
                raise FrameError('Backup imported, but unrelated cloud status is unsettled; library mode remains off')
            # Explicitly retained migration targets remain protected after restart.
            self.m.data['library_retained_indices'] = sorted(set(retain_indices) | self.protected())
            if recover_index is not None:
                await self.adopt(recover_index)
        elif self.cleanup_pending() or self.m.data.get('library_transaction', {}).get('stage') not in (None, 'complete'):
            raise FrameError('Resolve the durable library transaction before disabling library mode')
        self.m.data['library_mode'] = bool(enabled)
        await self.m.save_verified()
        return {'enabled': bool(enabled), 'protected_indices': sorted(self.protected()), 'cleanup_performed': False}

    async def adopt(self, index):
        """Reconcile a known legacy upload without registration or selection."""
        selected, stored, items = await self.snapshot()
        if index not in items:
            raise FrameError('Recovery slot is no longer in the catalogue; do not register a duplicate')
        existing = self.m.data.get('library_transaction')
        if existing and existing['stage'] != 'complete':
            if existing.get('new_index') != index or existing.get('new_identity') != self.identity(items[index]):
                raise FrameError('A different transaction is pending; recovery is not allowed')
            return
        raw = await self.m.read_image(items[index]['mainImageUrl'])
        gallery_id = await self.archive(index, items[index], raw=raw)
        self.m.data['library_transaction'] = {
            'sha256': hashlib.sha256(raw).hexdigest(), 'previous': None,
            'new_gallery_id': gallery_id, 'new_index': index, 'new_identity': self.identity(items[index]),
            'stage': 'complete' if index in stored and selected == index else 'awaiting_delivery',
            'adopted': True, 'release_requests': 0, 'delete_requests': 0, 'sync_requests': 0,
            'other_cloud': {str(i): self.identity(row) for i, row in items.items() if i != index},
        }
        if index in stored and selected == index:
            self.m.data.setdefault('library_reconciled_status',{})[str(index)]=self.identity(items[index])
        await self.m.save_verified()

    async def resume_delivery(self):
        """Explicit recovery of one adopted/registered image; never registers."""
        transaction = self.m.data.get('library_transaction', {})
        if not self.enabled() or transaction.get('stage') not in ('registered', 'awaiting_delivery'):
            raise FrameError('No existing image awaits delivery recovery')
        selected, stored, items = await self.snapshot()
        index = transaction['new_index']
        if self.restoration_active() or index not in items or self.identity(items[index]) != transaction['new_identity']:
            raise FrameError('Recovery paused: notification or image identity changed')
        await self.verify(transaction['new_gallery_id'])
        if transaction.get('adopted') and index not in stored:
            raise FrameError('Adopted recovery image is no longer stored; no download or registration attempted')
        if index not in stored:
            await self.m.client.download(index, 'frame1')
            await self.m.client.select_downloaded(index, 'frame1')
        elif selected != index:
            await self.m.client.show(index, 'frame1')
        return await self.confirm_delivery(index)

    async def stage(self, stage, **values):
        self.m.data['library_transaction'].update(stage=stage, **values)
        await self.m.save_verified()

    async def begin(self, content):
        selected, stored, items = await self.snapshot()
        if self.restoration_active() or self.m.data.get('pending_cloud_registration') or self.m.data.get('pending_replacement'):
            raise FrameError('Notification/restoration or uncertain transfer is active; nothing was removed')
        if self.unsettled(items):
            raise FrameError('Cloud status is unsettled; do not start another transfer')
        digest = hashlib.sha256(content).hexdigest()
        transaction = self.m.data.get('library_transaction')
        if transaction and transaction['stage'] in self.cleanup_stages:
            await self.enqueue_cleanup()
            transaction = self.m.data.get('library_transaction')
        if transaction and transaction['sha256'] == digest:
            new = transaction.get('new_index')
            if new is None and digest in self.m.data.get('cloud_art_uploads',{}):
                raise FrameError('Registration receipt needs explicit reconciliation; no duplicate image was registered')
            if new is not None and (new not in items or self.identity(items[new]) != transaction['new_identity']):
                raise FrameError('Previously registered slot changed; refusing stale-ledger reuse')
            await self.verify(transaction['new_gallery_id'])
            return transaction
        if transaction and transaction['stage'] != 'complete':
            raise FrameError('A different library transaction is pending; resume it explicitly')
        if digest in self.m.data.get('cloud_art_uploads', {}):
            raise FrameError('Legacy upload ledger has no library identity; reconcile before reuse')
        if len(stored) >= 10 or len(items) >= 10:
            raise FrameError('No spare capacity. Library mode never pre-deletes; verified manual bootstrap cleanup is required')
        previous = None
        if selected not in self.protected():
            if selected not in items:
                raise FrameError('Selected artwork has no cloud original; cannot prepare safe cleanup')
            previous = {'index': selected, 'identity': self.identity(items[selected])}
        # Preserve exactly the transport received by HA, not a fabricated phone original.
        new_id = await self.archive(0, {}, raw=content, known_layout=True)
        transaction = {'sha256': digest, 'previous': previous, 'new_gallery_id': new_id,
                       'new_index': None, 'stage': 'prepared', 'release_requests': 0,
                       'delete_requests': 0, 'sync_requests': 0,
                       'other_cloud': {str(i): self.identity(row) for i, row in items.items()
                                       if not previous or i != previous['index']}}
        self.m.data['library_transaction'] = transaction
        await self.m.save_verified()
        return transaction

    async def deliver(self, content):
        self.supported()
        if not self.enabled():raise FrameError('Opt into this frame library mode before sending through the library mode')
        transaction = await self.begin(content)
        index = await self.m.cloud_art(content)
        _, _, items = await self.snapshot()
        if index not in items:
            raise FrameError('Registered image is not visible in the catalogue; cleanup is suspended')
        if transaction.get('new_index') is not None and transaction['new_identity'] != self.identity(items[index]):
            raise FrameError('Registered image identity changed; cleanup is suspended')
        await self.stage('registered', new_index=index, new_identity=self.identity(items[index]))
        await self.m.client.download(index, 'frame1')
        # Existing production polling/selection stays unchanged, then independently
        # require both 9606 membership AND selected 9601 before any deletion.
        await self.m.client.select_downloaded(index, 'frame1')
        return await self.confirm_delivery(index)

    async def confirm_delivery(self, index):
        transaction = self.m.data['library_transaction']
        for attempt in range(40):
            selected, stored, items = await self.snapshot()
            if index in items and self.identity(items[index]) != transaction['new_identity']:
                raise FrameError('New slot was reused; cleanup suspended')
            if selected == index and index in stored and index in items:
                # A legacy status=0 is not itself proof of an active transfer.
                # Reconcile it only for this exact identity after both device
                # membership and selection are freshly confirmed.
                self.m.data.setdefault('library_reconciled_status',{})[str(index)]=self.identity(items[index])
                await self.stage('confirmed')
                await self.enqueue_cleanup()
                self.queue_cleanup()
                self.m.last_action = 'New artwork stored and selected; previous-slot cleanup queued'
                self.m.publish('art_selected')
                return {'accepted': True, 'local_storage_verified': True, 'display_verified': False,
                        'cloud_upload': True, 'transport': 'SwitchBot cloud / Wi-Fi', 'cleanup_pending': self.cleanup_pending()}
            if attempt < 39:
                await asyncio.sleep(3)
        await self.stage('awaiting_delivery')
        self.m.last_action = 'New upload accepted; storage/selection not both confirmed. Previous artwork retained.'
        self.m.publish('cloud_request_accepted')
        return {'accepted': True, 'local_storage_verified': False, 'display_verified': False,
                'library_cleanup': 'not attempted; delivery unconfirmed'}

    cleanup_stages = ('confirmed', 'device_release', 'device_absent', 'cloud_delete', 'cloud_sync', 'awaiting_absence')

    @staticmethod
    def describe(transaction):
        """Supported diagnostics: no cloud URLs, credentials or artwork bytes."""
        return {**{k: transaction.get(k) for k in ('stage', 'new_index', 'new_gallery_id',
                    'release_requests', 'delete_requests', 'sync_requests', 'result', 'error')},
                'previous_index': (transaction.get('previous') or {}).get('index'),
                'previous_backed_up': bool((transaction.get('previous') or {}).get('gallery_id'))}

    def cleanup_pending(self):
        return (self.m.data.get('library_transaction', {}).get('stage') in self.cleanup_stages
                or any(t.get('stage') != 'complete' for t in self.m.data.get('library_cleanup_queue', [])))

    async def enqueue_cleanup(self):
        """Atomically preserve legacy/new confirmation before replacing delivery intent."""
        transaction = self.m.data.get('library_transaction', {})
        if transaction.get('stage') not in self.cleanup_stages:
            return
        before = copy.deepcopy(self.m.data)
        queue = self.m.data.setdefault('library_cleanup_queue', [])
        # Idempotent migration; identity, not slot number, owns cleanup work.
        def key(t):
            previous = t.get('previous') or {}
            return t.get('new_identity'), previous.get('index'), previous.get('identity')
        if not any(key(t) == key(transaction) for t in queue):
            queue.append(copy.deepcopy(transaction))
        self.m.data['library_transaction'] = dict(transaction, stage='complete', result='delivery confirmed; cleanup queued')
        try:
            await self.m.save_verified()
        except BaseException:
            self.m.data.clear(); self.m.data.update(before)
            raise

    def queue_cleanup(self):
        """One background task, with Manager.lock serialization and durable intent."""
        task = getattr(self.m, 'library_cleanup_task', None)
        if task is not None and not task.done():
            return
        if not self.enabled() or not self.cleanup_pending():
            return
        async def run():
            try:
                # Bounded run, but each poll releases the lock for normal sends.
                for attempt in range(40):
                    async with self.m.lock:
                        try:
                            await self.cleanup()
                        except FrameError as error:
                            # A protected/stale intent must not starve another
                            # queued intent. Failed saves still gate all commands.
                            self.m.data['library_cleanup_error'] = str(error)
                            await self.m.save_verified()
                        self.m.publish(error=self.m.error)
                        if not self.cleanup_pending():
                            return
                    if attempt < 39:
                        await asyncio.sleep(3)
            except Exception as error:
                # Delivery already succeeded. Cleanup failure is a separate,
                # persisted state, not an upload failure or a reason to re-send.
                self.m.data['library_cleanup_error'] = type(error).__name__ + ': ' + str(error)
                try:await self.m.save_verified()
                except Exception:pass
                self.m.publish(error=self.m.error)
        self.m.library_cleanup_task = self.m.hass.async_create_background_task(run(), 'frame library cleanup')
        self.m.tasks.add(self.m.library_cleanup_task)
        self.m.library_cleanup_task.add_done_callback(self.m.tasks.discard)

    async def cleanup_snapshot(self, transaction, require_archive=True):
        selected, stored, items = await self.snapshot()
        # An older delivery need not still be selected. The fresh selected
        # image must exist, and the exact old target must not be selected.
        latest = self.m.data.get('library_transaction', {})
        index = selected
        if (not self.enabled() or self.restoration_active()
                or self.m.data.get('pending_cloud_registration') or self.m.data.get('pending_replacement')
                or latest.get('stage') != 'complete'
                or index not in stored or index not in items or self.unsettled(items)):
            raise FrameError('Cleanup paused: new selection, catalogue or notification state is not safe')
        previous = transaction['previous']
        if previous:
            old = previous['index']
            if old in self.protected() or old == selected:
                raise FrameError('Previous slot is now a restoration/notification reference; keep it')
            if old in items and self.identity(items[old]) != previous['identity']:
                raise FrameError('Previous slot was reused; refusing deletion')
            if require_archive:await self.verify(previous['gallery_id'])
        await self.verify(transaction['new_gallery_id'])
        return stored, items

    async def cleanup(self):
        """One bounded pass; no polling sleeps while the caller owns the lock."""
        self.supported()
        await self.enqueue_cleanup()
        queue = self.m.data.get('library_cleanup_queue', [])
        if not self.cleanup_pending():
            return 'nothing pending'
        errors = []
        for transaction in queue:
            if transaction.get('stage') == 'complete':
                continue
            try:
                await self.cleanup_step(transaction)
                transaction.pop('error', None)
            except Exception as error:
                transaction['error'] = type(error).__name__ + ': ' + str(error)
                errors.append(error)
            await self.m.save_verified()
        if errors:
            raise errors[0]
        self.m.data.pop('library_cleanup_error', None)
        await self.m.save_verified()
        return 'cleanup pending' if self.cleanup_pending() else 'previous archived and removed after new selection'

    async def cleanup_step(self, transaction):
        if transaction.get('stage') not in self.cleanup_stages:
            raise FrameError('No durable delivery confirmation; no deletion allowed')
        async def stage(value, **values):
            transaction.update(stage=value, **values)
            await self.m.save_verified()
        await self.m.save_verified()
        if not transaction['previous']:
            await stage('complete', result='previous retained: protected reference')
            return
        old = transaction['previous']['index']
        if not transaction['previous'].get('gallery_id'):
            _, items = await self.cleanup_snapshot(transaction, require_archive=False)
            if old not in items:
                raise FrameError('Previous source disappeared before archival; cleanup paused')
            gallery_id = await self.archive(old, items[old])
            previous = dict(transaction['previous'],gallery_id=gallery_id)
            await stage(transaction['stage'],previous=previous)
        stored, items = await self.cleanup_snapshot(transaction)
        if old not in stored and old not in items:
            # Reconcile completed remote work before checking exhausted budgets.
            ledger = self.m.data.get('cloud_art_uploads', {})
            for digest in [digest for digest, value in ledger.items() if value == old]:
                del ledger[digest]
            await stage('complete', result='previous archived and absence verified')
            return
        # Match the already-proven Frame1 replacement transaction: wake/release,
        # cloud delete, sync, THEN verify absence. Device membership may remain
        # reported until the cloud deletion has been synchronised.
        if (old in stored or old in items) and transaction.get('wake_requests',0)<2:
            await stage(transaction['stage'],wake_requests=transaction.get('wake_requests',0)+1)
            await self.m.client.invoke(9609)
            return
        if old in stored:
            if old not in items and not transaction['release_requests']:
                raise FrameError('Stored-only previous slot has no verifiable cloud identity; no release attempted')
            if old in items and transaction['release_requests'] < 2:
                await stage('device_release', release_requests=transaction['release_requests'] + 1)
                await self.m.client.invoke(9601, {'0': 2, '1': old})
            # A persisted exhausted release budget does not mean deletion is
            # unapproved: earlier attempts are already recorded. Resume the
            # pending cloud half without issuing a third release.
        for counter, next_stage, endpoint, key in (
            ('delete_requests', 'cloud_delete', '/device/artframe/api/v1/images/delete', 'imageIndexList'),
            ('sync_requests', 'cloud_sync', '/productbiz/v1/slideshow/syncDeletedImages', 'imageIndexes'),
        ):
            stored, items = await self.cleanup_snapshot(transaction)
            needed = old in items if counter == 'delete_requests' else (not transaction.get('sync_confirmed') or old in stored)
            if needed:
                if transaction[counter] >= 2:
                    raise FrameError('Cloud cleanup budget exhausted; no other slot was touched')
                transaction.update(stage=next_stage, **{counter: transaction[counter] + 1})
                await self.m.save_verified()
                await self.m.client.post(endpoint, {'deviceID': self.m.client.device,
                    'groupID': self.m.client.group, key: [old], 'deleteAll': False})
                if counter == 'sync_requests':
                    transaction['sync_confirmed'] = True
                    await self.m.save_verified()
        transaction['stage'] = 'awaiting_absence'
        await self.m.save_verified()

