"""Upload first; durable identity-bound cleanup never reserves spare capacity.

Entry points and individual cleanup steps hold Manager.lock. Polling waits do
not. Cleanup intents survive subsequent deliveries, failures and restarts.
"""
import asyncio
import base64
import copy
import hashlib
import json
import time
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

    def automatic_protected(self):
        # Preserve the entire existing normal-restore set, not just notifications.
        # No migration/re-upload of those references is attempted by this pilot.
        result = set(self.m.protected_indices()) | set(self.m.data['normal_indices'])
        reminder = self.m.hass.data.get('frame_bin_reminder')
        if reminder is not None and getattr(reminder, 'manager', None) is self.m:
            for value in (reminder.data.get('slot', {}).get('index'),
                          reminder.data.get('snapshot', {}).get('index')):
                if type(value) is int:
                    result.add(value)
        return result

    def protected(self):
        return self.automatic_protected() | set(self.m.data.get('library_retained_indices', []))

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
        transaction = self.current_operation()
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
        before = copy.deepcopy(self.m.data)
        try:
            return await self._set_enabled(enabled, retain_indices, recover_index)
        except BaseException:
            self.m.data.clear(); self.m.data.update(before)
            raise

    async def _set_enabled(self, enabled, retain_indices, recover_index=None):
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
            # Replace only explicit choices; automatic restore protections stay dynamic.
            self.m.data['library_retained_indices'] = sorted(set(retain_indices))
            if recover_index is not None:
                await self.adopt(recover_index)
        elif self.m.data.get('library_transaction', {}).get('stage') not in (None, 'complete'):
            raise FrameError('Resolve the durable library transaction before disabling the pilot')
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
        if not self.enabled() or transaction.get('stage') not in ('registered', 'awaiting_delivery', 'prepared', 'registering'):
            raise FrameError('No existing image awaits delivery recovery')
        await self.verify(transaction['new_gallery_id'])
        self.queue_delivery()
        return self.delivery_response()

    async def stage(self, stage, **values):
        before = copy.deepcopy(self.m.data)
        self.m.data['library_transaction'].update(stage=stage, **values)
        try:
            await self.m.save_verified()
        except BaseException:
            self.m.data.clear(); self.m.data.update(before)
            raise

    async def begin(self, content):
        selected, stored, items = await asyncio.wait_for(self.snapshot(), self.command_timeout)
        if self.restoration_active() or self.m.data.get('pending_replacement'):
            raise FrameError('Notification/restoration or uncertain transfer is active; nothing was removed')
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
            if set(self.unsettled(items)) - ({new} if new is not None else set()):
                raise FrameError('Unrelated cloud status is unsettled; delivery paused')
            return transaction
        if self.m.data.get('pending_cloud_registration'):
            raise FrameError('Registration outcome is uncertain; reconcile without another upload')
        if self.unsettled(items):
            raise FrameError('Cloud status is unsettled; do not start another transfer')
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
        if not self.enabled():raise FrameError('Opt into this frame library mode before sending through the library pilot')
        transaction = await self.begin(content)
        if transaction.get('stage') == 'complete':
            selected, stored, items = await self.snapshot()
            if selected == transaction.get('new_index') and selected in stored:
                return self.delivery_response()
            await self.stage('awaiting_delivery')
        self.queue_delivery()
        return self.delivery_response()

    def current_operation(self):
        submission = self.m.data.get('library_submission')
        if submission:
            return {'stage': submission['stage'], 'error': submission.get('error'),
                    'operation_id': submission['sha256'],
                    'delivery': {'phase': submission.get('phase', 'source_saved'), 'download_attempts': 0,
                                 'selection_attempts': 0}}
        return self.m.data.get('library_transaction', {})

    async def submit(self, raw):
        """Normal HTTP path: durable exact bytes, no image work or vendor I/O.

        Caller holds Manager.lock. Disk persistence is required before acceptance;
        all image decoding, archive presentation, network and registration is queued.
        """
        self.supported()
        if not self.enabled():
            raise FrameError('Opt into this frame library mode before sending')
        if not isinstance(raw, bytes) or not 0 < len(raw) <= 8*1024*1024:
            raise FrameError('Invalid or oversized source')
        digest = hashlib.sha256(raw).hexdigest()
        submission = self.m.data.get('library_submission')
        t = self.m.data.get('library_transaction', {})
        if t.get('stage') in self.cleanup_stages:
            await self.enqueue_cleanup()
            t = self.m.data['library_transaction']
        if submission:
            if submission['sha256'] != digest:
                raise FrameError('A different source is pending; no new registration attempted')
        elif digest in (t.get('request_sha256'), t.get('sha256')):
            # The worker, not this HTTP call, validates fresh identity/status.
            if t.get('stage') == 'complete':
                await self.stage('awaiting_delivery')
        else:
            if (self.restoration_active() or self.m.data.get('pending_cloud_registration')
                    or self.m.data.get('pending_replacement')
                    or t.get('stage') not in (None, 'complete')):
                raise FrameError('Different delivery or uncertain transfer is active; no new registration attempted')
            before = copy.deepcopy(self.m.data)
            self.m.data['library_submission'] = {'stage': 'prepared', 'sha256': digest,
                'source_b64': base64.b64encode(raw).decode('ascii'),
                'created_at': time.time(), 'layout': copy.deepcopy(self.m.data['layout'])}
            try:
                await self.m.save_verified()
            except BaseException:
                self.m.data.clear(); self.m.data.update(before)
                raise
        self.queue_delivery()
        self.m.last_action = 'Exact source saved; preparation and cloud/device delivery are pending'
        op = self.current_operation()
        self.m.publish('delivery_pending' if op.get('stage') in self.delivery_stages else op.get('stage'))
        return self.delivery_response()

    async def confirm_delivery(self, index, observed=None):
        """Single fresh confirmation, never a second long polling window."""
        transaction = self.m.data['library_transaction']
        selected, stored, items = observed if observed is not None else await asyncio.wait_for(self.snapshot(), self.command_timeout)
        if index not in items or self.identity(items[index]) != transaction['new_identity']:
            raise FrameError('New slot was reused; cleanup suspended')
        if selected == index and index in stored:
            # Cloud status alone is not delivery; both device fields were checked.
            self.m.data.setdefault('library_reconciled_status',{})[str(index)]=self.identity(items[index])
            await self.stage('confirmed')
            try:
                await self.enqueue_cleanup()
            except Exception:
                # Confirmed delivery is durable even if queue migration failed.
                self.m.last_action = 'Device delivery verified; cleanup persistence pending'
                self.m.publish('art_selected')
                return True
            else:
                self.queue_cleanup()
                self.m.last_action = 'New artwork stored and selected; previous-slot cleanup queued'
                self.m.publish('art_selected')
                return True
        return False

    delivery_stages = ('prepared', 'registering', 'registered', 'awaiting_delivery')
    max_attempts = 2
    storage_polls = 40
    selection_polls = 20
    command_timeout = 20
    registration_timeout = 180
    delivery_timeout = 600

    def delivery_response(self):
        t = self.current_operation()
        return {'accepted': True, 'pending': t.get('stage') in self.delivery_stages,
                'local_storage_verified': t.get('stage') == 'complete' or t.get('stage') in self.cleanup_stages,
                'display_verified': False, 'delivery': self.describe(t),
                'cleanup_pending': self.cleanup_pending()}

    async def progress(self, phase, **values):
        t = self.m.data['library_transaction']
        delivery = dict(t.get('delivery', {}), phase=phase, updated_at=time.time(), **values)
        await self.stage(t['stage'], delivery=delivery)
        self.m.last_action = 'Delivery: ' + phase.replace('_', ' ') + '; physical display not verified'
        self.m.publish('delivery_pending')

    async def stop_delivery(self, stage, reason):
        if self.m.data.get('library_submission'):
            before = copy.deepcopy(self.m.data)
            self.m.data['library_submission'].update(stage=stage, error=reason)
            try:
                await self.m.save_verified()
            except BaseException:
                self.m.data.clear(); self.m.data.update(before)
                raise
        else:
            await self.stage(stage, error=reason)
        self.m.last_action = reason + '; previous artwork retained. Do not upload a duplicate.'
        self.m.publish(stage, error=reason)

    def queue_delivery(self):
        task = getattr(self.m, 'library_delivery_task', None)
        if task is not None and not task.done():
            return
        if not self.enabled() or self.current_operation().get('stage') not in self.delivery_stages:
            return

        async def run():
            try:
                while True:
                    async with self.m.lock:
                        delay = await self.delivery_step()
                    if delay is None:
                        return
                    # Never hold Manager.lock over wake-settling or polling waits.
                    await asyncio.sleep(delay)
            except asyncio.CancelledError:
                # Every command intent/budget was saved first; restart resumes observation.
                raise
            except Exception:
                async with self.m.lock:
                    try:
                        await self.stop_delivery('delivery_error', 'Delivery state could not be verified or persisted')
                    except Exception:
                        # Persistence is unhealthy: do not issue further commands.
                        self.m.publish('delivery_error', error='Delivery persistence failed; recovery paused')

        self.m.library_delivery_task = self.m.hass.async_create_background_task(run(), 'frame library delivery')
        self.m.tasks.add(self.m.library_delivery_task)
        self.m.library_delivery_task.add_done_callback(self.m.tasks.discard)

    async def delivery_step(self):
        """One serialized bounded step. Only this worker registers/downloads/selects."""
        submission = self.m.data.get('library_submission')
        if submission:
            if submission['stage'] != 'prepared':
                return None
            try:
                if time.time() >= submission['created_at'] + self.delivery_timeout:
                    await self.stop_delivery('delivery_exhausted', 'Preparation deadline exhausted; source retained')
                    return None
                if submission['layout'] != self.m.data['layout']:
                    raise FrameError('Saved layout changed during preparation')
                raw = base64.b64decode(submission['source_b64'], validate=True)
                if hashlib.sha256(raw).hexdigest() != submission['sha256']:
                    raise FrameError('Saved exact source changed')
                submission.update(phase='preparing_source', updated_at=time.time())
                await self.m.save_verified()
                self.m.last_action = 'Preparing durable source; cloud registration not yet started'
                self.m.publish('delivery_pending')
                remaining = submission['created_at']+self.delivery_timeout-time.time()
                content = await asyncio.wait_for(self.m.prepare_library_source(raw), min(self.registration_timeout, max(.01, remaining)))
                await self.begin(content)
            except asyncio.CancelledError:
                raise
            except Exception:
                await self.stop_delivery('delivery_error', 'Source preparation or readiness verification failed; source retained')
                return None
            before = copy.deepcopy(self.m.data)
            self.m.data['library_transaction']['request_sha256'] = submission['sha256']
            if self.m.data['library_transaction']['stage'] == 'complete':
                self.m.data['library_transaction']['stage'] = 'awaiting_delivery'
            self.m.data['library_transaction'].setdefault('delivery', {
                'phase': 'ready', 'started_at': submission['created_at'],
                'deadline': submission['created_at']+self.delivery_timeout,
                'download_attempts': 0, 'selection_attempts': 0, 'polls': 0})
            self.m.data.pop('library_submission')
            try:
                await self.m.save_verified()
            except BaseException:
                self.m.data.clear(); self.m.data.update(before)
                raise
            return 0
        t = self.m.data.get('library_transaction', {})
        if not self.enabled() or t.get('stage') not in self.delivery_stages:
            return None
        now = time.time()
        d = t.get('delivery', {})
        if d and now < d.get('started_at', now)-5:
            await self.stop_delivery('delivery_error', 'Clock moved backwards; delivery paused for review')
            return None
        if not d:
            await self.progress('ready', started_at=now, deadline=now+self.delivery_timeout,
                                download_attempts=0, selection_attempts=0, polls=0)
            d = self.m.data['library_transaction']['delivery']
        # Read-only fresh evidence always precedes retries, including lost replies.
        try:
            selected, stored, items = await asyncio.wait_for(self.snapshot(), self.command_timeout)
        except Exception:
            failures = d.get('snapshot_failures', 0) + 1
            if failures >= 3 or now >= d['deadline']:
                await self.stop_delivery('delivery_error', 'Fresh device/catalogue observation failed')
                return None
            await self.progress(d['phase'], snapshot_failures=failures)
            return 3
        if self.restoration_active() or self.m.data.get('pending_replacement'):
            await self.stop_delivery('delivery_error', 'Notification or restoration interrupted delivery')
            return None
        index = t.get('new_index')
        if index is None:
            if now >= d['deadline']:
                await self.stop_delivery('delivery_exhausted', 'Registration deadline exhausted; inspect before retry')
                return None
            if (t['stage'] != 'prepared' or d.get('registration_attempts', 0)
                    or self.m.data.get('pending_cloud_registration')
                    or t['sha256'] in self.m.data.get('cloud_art_uploads', {})):
                await self.stop_delivery('delivery_error', 'Registration outcome requires explicit reconciliation')
                return None
            if self.unsettled(items) or len(items) >= 10 or len(stored) >= 10:
                await self.stop_delivery('delivery_error', 'Cloud status or capacity changed before registration')
                return None
            content = await self.verify(t['new_gallery_id'])
            if hashlib.sha256(content).hexdigest() != t['sha256']:
                await self.stop_delivery('delivery_error', 'Saved upload fingerprint changed')
                return None
            await self.progress('registering', registration_attempts=1)
            await self.stage('registering')
            try:
                remaining = d['deadline']-time.time()
                if remaining <= 0:
                    await self.stop_delivery('delivery_exhausted', 'Registration deadline exhausted; inspect before retry')
                    return None
                index = await asyncio.wait_for(self.m.cloud_art(content), min(self.registration_timeout, remaining))
                _, _, items = await asyncio.wait_for(self.snapshot(), self.command_timeout)
                if index not in items:
                    raise FrameError('Registration not visible')
            except Exception:
                await self.stop_delivery('delivery_error', 'Registration outcome requires explicit reconciliation')
                return None
            await self.stage('awaiting_delivery', new_index=index, new_identity=self.identity(items[index]))
            return 0
        if index not in items or self.identity(items[index]) != t.get('new_identity'):
            await self.stop_delivery('delivery_error', 'Registered image identity changed; no commands sent')
            return None
        if set(self.unsettled(items)) - {index}:
            await self.stop_delivery('delivery_error', 'Unrelated cloud image is unsettled; delivery paused')
            return None
        if self.m.data.get('pending_cloud_registration'):
            await self.stop_delivery('delivery_error', 'Another registration outcome is uncertain; delivery paused')
            return None
        await self.verify(t['new_gallery_id'])
        now = time.time()
        if selected == index and index in stored:
            await self.confirm_delivery(index, (selected, stored, items))
            return None
        if now >= d['deadline']:
            await self.stop_delivery('delivery_exhausted', 'Delivery deadline exhausted')
            return None
        due = d.get('next_at', 0)
        if due > now:
            return min(3, due-now)
        if index in stored:
            attempts = d.get('selection_attempts', 0)
            if d['phase'] == 'waiting_selection' and d.get('polls', 0) < self.selection_polls:
                await self.progress('waiting_selection', polls=d.get('polls', 0)+1)
                return 3
            if attempts >= self.max_attempts:
                await self.stop_delivery('delivery_exhausted', 'Selection acknowledgement was not verified')
                return None
            await self.progress('waiting_selection', selection_attempts=attempts+1, polls=0)
            try:
                await asyncio.wait_for(self.m.client.show(index, 'frame1'), self.command_timeout)
            except Exception:
                await self.progress('waiting_selection', last_command='selection_reply_lost_or_rejected')
            return 3
        if d['phase'] == 'waiting_storage' and d.get('polls', 0) < self.storage_polls:
            await self.progress('waiting_storage', polls=d.get('polls', 0)+1)
            return 3
        if d['phase'] == 'wake_settling':
            # download() also wakes on frame1; invoke the app's add command only
            # after our persisted wake-settle interval, without duplicate polling.
            await self.progress('waiting_storage', polls=0)
            try:
                await asyncio.wait_for(self.m.client.invoke(9601, {'0':1, '1':index}), self.command_timeout)
            except Exception:
                await self.progress('waiting_storage', last_command='download_reply_lost_or_rejected')
            return 3
        attempts = d.get('download_attempts', 0)
        if attempts >= self.max_attempts:
            await self.stop_delivery('delivery_exhausted', 'Download acknowledgement was not verified')
            return None
        await self.progress('wake_settling', download_attempts=attempts+1, polls=0, next_at=now+5)
        try:
            await asyncio.wait_for(self.m.client.invoke(9609), self.command_timeout)
        except Exception:
            await self.progress('wake_settling', last_command='wake_reply_lost_or_rejected')
        return 5

    cleanup_stages = ('confirmed', 'device_release', 'device_absent', 'cloud_delete', 'cloud_sync', 'awaiting_absence')

    @staticmethod
    def describe(transaction):
        """Supported diagnostics: no cloud URLs, credentials or artwork bytes."""
        return {**{k: transaction.get(k) for k in ('stage', 'new_index', 'new_gallery_id',
                    'release_requests', 'delete_requests', 'sync_requests', 'result', 'error', 'delivery')},
                'operation_id': transaction.get('operation_id') or transaction.get('request_sha256') or transaction.get('sha256'),
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

    async def cleanup_device_slots(self, indices):
        """Excluded installation-specific migration bridge; fail closed."""
        raise FrameError('Installation-specific device migration is not included in this source export')
