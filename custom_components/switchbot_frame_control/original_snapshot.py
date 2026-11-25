"""Live original-frame status and mode references, never shadow membership.

Only the supplied original-frame wire layout/static preset is supported. Unknown
modes fail closed; an idle download byte is not evidence of failed storage.
"""
import asyncio
import time

from .live_reply import LiveReplyTransport
from .protocol import FrameError

PROFILES = {'13.3': 0x10, '31.5': 0x20}


def is_live_original(manager):
    return manager.config.get('model') == 'frame1' and manager.config.get('panel_size') in PROFILES


def status_bytes(params):
    try:
        value = params['1']['0']
        if not isinstance(value, str) or not 2 <= len(value) <= 128 or len(value) % 2:
            raise ValueError
        raw = bytes.fromhex(value)
        if len(raw) * 2 != len(value):
            raise ValueError
        return raw
    except (KeyError, TypeError, ValueError):
        raise FrameError('Malformed original-frame live status') from None


def membership(raw, count_at):
    if len(raw) <= count_at:
        raise FrameError('Truncated original-frame live status')
    count = raw[count_at]
    indices = list(raw[count_at+1:count_at+1+count])
    if count > 10 or len(indices) != count or 0 in indices or len(set(indices)) != count:
        raise FrameError('Invalid original-frame live membership')
    return sorted(indices)


def decode_9600(params, size_code):
    raw = status_bytes(params)
    stored = membership(raw, 6)
    if (raw[0] != 1 or raw[1] > 100 or raw[5] == 0 or raw[3] != 1
            or raw[4] & 0xf0 != size_code or raw[2] not in (12, 14)):
        raise FrameError('Invalid original-frame live selection/battery')
    # Only the two verified firmware codes are accepted in this candidate.
    return {'selected_index': raw[5], 'stored_indices': stored, 'battery': raw[1],
            'firmware': {12: '1.2', 14: '1.4'}[raw[2]], 'size_code': raw[4] & 0xf0}


def decode_9603(params):
    raw = status_bytes(params)
    stored = membership(raw, 4)
    if (raw[0] != 1 or raw[3] not in (0, 1, 2, 3)
            or any(not 48 <= value <= 57 for value in raw[1:3])):
        raise FrameError('Invalid original-frame live download status')
    return {'stored_indices': stored, 'download_status': raw[3],
            'connectivity_ascii': raw[1:3].decode('ascii')}


def decode_9606(params):
    try:
        mode = params['1']
        if not isinstance(mode, dict) or type(mode['0']) is not int or not 0 <= mode['0'] <= 255:
            raise ValueError
        if mode['0'] != 0:
            # Current/storage are still decoded from fresh info, never inferred
            # from an unknown mode payload. Destructive consumers must fail closed.
            return {'mode': 'undecoded', 'mode_code': mode['0'],
                    'mode_reference_indices': [], 'mode_references_complete': False}
        static = mode['1']
        if (not isinstance(static, dict) or type(static['0']) is not int
                or not 1 <= static['0'] <= 255
                or any(type(static[k]) is not int or static[k] not in (0, 1) for k in ('1', '2'))):
            raise ValueError
        return {'mode': 'static', 'mode_code': 0, 'mode_reference_indices': [static['0']],
                'mode_references_complete': True}
    except (KeyError, TypeError, ValueError):
        raise FrameError('Unsupported mode references; retain all prior artwork') from None


class OriginalSnapshot:
    def __init__(self, manager, *, transport_factory=LiveReplyTransport):
        self.m = manager
        self.transport_factory = transport_factory

    def supported(self):
        profile = PROFILES.get(self.m.config.get('panel_size'))
        if (profile is None or self.m.config.get('model') != 'frame1'
                or self.m.client.seed.get('region', 'eu') != 'eu'
                or self.m.connection_mode() not in ('wifi', 'hybrid')):
            raise FrameError('Live snapshot requires a configured supported original Wi-Fi profile')

    async def read(self):
        self.supported()
        app = self.m.client
        if getattr(app, '_live_closing', False):
            raise FrameError('Live diagnostics are stopping')
        started = time.monotonic()
        transport = self.transport_factory(app)
        app._live_transports.add(transport)
        try:
            async with asyncio.timeout(50):
                async with transport:
                    # Snapshot freshness starts after provisioning/subscription.
                    started = time.monotonic()
                    status = await transport.query(9600)
                    download = await transport.query(9603)
                    mode = await transport.query(9606)
                    if time.monotonic()-started > 15:
                        raise FrameError('Live status collection exceeded freshness window')
                    selected = decode_9600(status['params'], PROFILES[self.m.config['panel_size']])
                    downloading = decode_9603(download['params'])
                    references = decode_9606(mode['params'])
                    if (selected['stored_indices'] != downloading['stored_indices']
                            or selected['selected_index'] not in selected['stored_indices']):
                        raise FrameError('Live status reads disagree; do not reconcile')
                    rows = await app.catalogue()
                    if time.monotonic()-started > 15:
                        raise FrameError('Catalogue delayed live snapshot beyond freshness window')
        finally:
            app._live_transports.discard(transport)
        if time.monotonic()-started > 15:
            raise FrameError('Live snapshot expired while closing the session')
        if (not isinstance(rows, list) or any(not isinstance(row, dict)
                or type(row.get('imageIndex')) is not int or not 1 <= row['imageIndex'] <= 255 for row in rows)):
            raise FrameError('Invalid live snapshot catalogue')
        items = {row['imageIndex']: row for row in rows}
        if len(items) != len(rows):
            raise FrameError('Duplicate catalogue indices; do not reconcile')
        evidence = [{key: reply[key] for key in (
            'function', 'sent_at', 'received_at', 'reply_at', 'request_sha256')}
            for reply in (status, download, mode)]
        # Read-only runtime protection; never remove a prior reference here.
        # Durable protection is written only by explicit local settlement.
        app.mode_references = set(references['mode_reference_indices'])
        app.mode_references_complete = references['mode_references_complete']
        return {'selected_index': selected['selected_index'], 'stored_indices': selected['stored_indices'],
                'battery': selected['battery'], 'firmware': selected['firmware'],
                'size_code': selected['size_code'], **references,
                'download_status': downloading['download_status'],
                'connectivity_ascii': downloading['connectivity_ascii'],
                'membership_kind': 'live_correlated_9600_and_9603',
                'physical_panel_verified': False, 'observed_at': time.time(),
                'evidence': evidence, 'items': items}

    @staticmethod
    def describe(snapshot):
        return {key: value for key, value in snapshot.items() if key != 'items'}
