"""Original-frame read-only, nonce-bound IoT replies. Never log wire bodies.

No reconnect/resend, wildcard topics, system trust changes or persistent keys.
All paho callbacks hand immutable input to the owning asyncio event loop.
"""
import asyncio
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import ssl
import tempfile
import time
import uuid

from .protocol import FrameError

BROKER = 'core.broker.iot.eu.switchbot.net'
CA_SHA256 = '2be94ff0f723d9209f361bc06fcb4ca9103ee7edc964a82c354cf424494ca860'
READ_FUNCTIONS = frozenset((9600, 9603, 9606))
MAX_MESSAGE = 16384


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


def account_id(token):
    """Routing claim only; JWT authentication remains the vendor's responsibility."""
    try:
        part = token.split('.')[1]
        data = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
        value = data.get('userID') or data['sub']
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
            raise ValueError
        return value
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise FrameError('Invalid MQTT account binding') from None


def certificate_context(p12_bytes, ca_path=None):
    """Blocking: run in executor. Private key files are short-lived 0600/0700."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12
    try:
        ca = (ca_path or Path(__file__).with_name('assets') / 'prd_ca.pem').read_bytes()
        if hashlib.sha256(ca).hexdigest() != CA_SHA256:
            raise ValueError
        key, cert, chain = pkcs12.load_key_and_certificates(p12_bytes, b'12345678')
        if key is None or cert is None:
            raise ValueError
        # No OS CA import: trust only the checked public production CA here.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.verify_mode = ssl.CERT_REQUIRED
        context.check_hostname = True
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_verify_locations(cadata=ca.decode('ascii'))
        # tempfile uses exclusive private names; permissions set before writing.
        with tempfile.TemporaryDirectory(prefix='switchbot-frame-mtls-') as directory:
            os.chmod(directory, 0o700)
            cert_path = Path(directory) / 'client.pem'
            key_path = Path(directory) / 'key.pem'
            certificate = cert.public_bytes(serialization.Encoding.PEM)
            certificate += b''.join(c.public_bytes(serialization.Encoding.PEM) for c in chain or ())
            private = key.private_bytes(serialization.Encoding.PEM,
                                        serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption())
            for path, content in ((cert_path, certificate), (key_path, private)):
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(content)
            context.load_cert_chain(str(cert_path), str(key_path))
        return context
    except Exception:
        raise FrameError('MQTT certificate preparation failed') from None


class LiveReplyTransport:
    """One short-lived session. Only status-query functions can be invoked."""
    def __init__(self, app, *, mqtt_factory=None, context_factory=certificate_context,
                 request_timeout=10, ready_timeout=15, clock=time.time,
                 monotonic=time.monotonic):
        self.app = app
        self.device = app.device
        self.mqtt_factory = mqtt_factory
        self.context_factory = context_factory
        self.request_timeout = request_timeout
        self.ready_timeout = ready_timeout
        self.clock, self.monotonic = clock, monotonic
        self.client = None
        self.pending = None
        self.closed = False
        self.failed = False
        self.subscription_mid = None
        self.startup = None
        self.work = None
        self.loop = asyncio.get_running_loop()
        self.ready = self.loop.create_future()
        self.query_lock = asyncio.Lock()
        self.close_lock = asyncio.Lock()

    def _dispatch(self, function, *args):
        if not self.loop.is_closed():
            try:
                self.loop.call_soon_threadsafe(function, *args)
            except RuntimeError:
                pass  # Event loop shut down between the check and dispatch.

    def _fail(self):
        self.failed = True
        for future in (self.ready, self.pending['future'] if self.pending else None):
            if future is not None and not future.done():
                future.set_exception(FrameError('Live reply connection unavailable; outcome unknown'))

    def _connected(self, reason):
        if self.closed or self.failed:
            return
        if reason.is_failure:
            self._fail()
            return
        try:
            code, self.subscription_mid = self.client.subscribe(self.topic, qos=0)
            if code != 0:
                self._fail()
        except Exception:
            self._fail()

    def _subscribed(self, mid, reasons):
        if self.closed or self.failed:
            return
        if mid != self.subscription_mid or not reasons or any(r.is_failure for r in reasons):
            self._fail()
        elif not self.ready.done():
            self.ready.set_result(True)

    def _message(self, topic, retained, raw, received_wall, received_mono):
        p = self.pending
        if (self.closed or self.failed or topic != self.topic or retained or not p
                or p['future'].done() or len(raw) > MAX_MESSAGE):
            return
        try:
            body = json.loads(raw, object_pairs_hook=unique_object)
            payload = body['payload']
            stamp = payload['timestamp']
            if type(stamp) not in (int, float) or not math.isfinite(stamp):
                return
            stamp = stamp / 1000 if stamp > 100000000000 else stamp
            params = payload['params']
            if (type(body.get('version')) not in (int, str)
                    or not str(body['version']) or len(str(body['version'])) > 16
                    or body.get('deviceID') != self.device
                    or type(body.get('code')) is not int or body['code'] != 4
                    or type(payload.get('funcID')) is not int or payload['funcID'] != p['function']
                    or payload.get('requestID') != p['request']
                    or type(payload.get('resultCode')) is not int or payload['resultCode'] != 200
                    or not isinstance(params, dict) or type(params.get('0')) is not int or params['0'] != 1
                    or not 0 <= received_mono - p['sent_mono'] <= self.request_timeout
                    or not p['sent_wall'] - 2 <= stamp <= received_wall + 2
                    or not -2 <= received_wall - stamp <= 15
                    or abs((received_wall-p['sent_wall'])-(received_mono-p['sent_mono'])) > 2):
                return
            reply = {'params': params, 'function': p['function'], 'sent_at': p['sent_wall'],
                     'received_at': received_wall, 'reply_at': stamp,
                     'request_sha256': hashlib.sha256(p['request'].encode()).hexdigest()}
        except (KeyError, TypeError, ValueError, OverflowError):
            return
        if p['accepted']:
            p['future'].set_result(reply)
        elif p['early'] is None:
            # Keep at most one validated reply; never accept it before HTTP ID.
            p['early'] = reply

    async def _thread(self, function, *args):
        # Shield blocking startup/crypto work, then join it before cleanup even
        # on cancellation (connect_timeout bounds paho's connection attempt).
        self.work = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(self.work)
        except asyncio.CancelledError:
            await asyncio.shield(self.work)
            raise
        finally:
            self.work = None

    async def __aenter__(self):
        try:
            await self.app.authenticate()
            self.user = account_id(self.app.headers.get('authorization'))
            installation = str(uuid.uuid4()).upper()
            self.client_id = f'APP_Android_{self.user}_{installation}'
            self.topic = f'v1_1/{self.user}/{installation}/response'
            if self.closed or getattr(self.app, '_live_closing', False):
                raise FrameError('Live transport is stopping')
            p12_bytes = await self.app.policy_certificate(self.client_id, self.user)
            context = await self._thread(self.context_factory, p12_bytes)
            del p12_bytes
            if self.closed:
                raise FrameError('Live transport is stopping')
            if self.mqtt_factory is None:
                import paho.mqtt.client as mqtt
                factory = mqtt.Client
                version = mqtt.CallbackAPIVersion.VERSION2
            else:
                factory, version = self.mqtt_factory, 2
            self.client = factory(version, client_id=self.client_id, clean_session=True,
                                  reconnect_on_failure=False)
            self.client.connect_timeout = 10
            self.client.max_inflight_messages_set(1)
            self.client.max_queued_messages_set(1)
            self.client.tls_set_context(context)
            self.client.on_connect = lambda c, u, flags, reason, props: self._dispatch(self._connected, reason)
            self.client.on_subscribe = lambda c, u, mid, reasons, props: self._dispatch(self._subscribed, mid, reasons)
            self.client.on_disconnect = lambda c, u, flags, reason, props: self._dispatch(self._fail)

            def message(c, userdata, msg):
                if len(msg.payload) <= MAX_MESSAGE:
                    self._dispatch(self._message, msg.topic, bool(msg.retain), bytes(msg.payload),
                                   self.clock(), self.monotonic())
            self.client.on_message = message

            def start():
                if self.client.connect(BROKER, 8883, keepalive=60) != 0:
                    raise FrameError('Live MQTT connection refused')
                if self.client.loop_start() != 0:
                    raise FrameError('Live MQTT network loop failed')
            await self._thread(start)
            await asyncio.wait_for(asyncio.shield(self.ready), self.ready_timeout)
            if self.closed or self.failed:
                raise FrameError('Live transport is stopping')
            return self
        except BaseException as error:
            await self.aclose()
            if isinstance(error, asyncio.CancelledError):
                raise
            raise FrameError('Live MQTT setup failed; no device query sent') from None

    async def query(self, function):
        if type(function) is not int or function not in READ_FUNCTIONS:
            raise FrameError('Only original-frame status queries are allowed')
        async with self.query_lock:
            if self.closed or self.failed or not self.ready.done() or self.ready.cancelled() or self.ready.exception():
                raise FrameError('Live reply subscription is not ready')
            request = str(uuid.uuid4()).upper()
            future = self.loop.create_future()
            self.pending = {'request': request, 'function': function, 'future': future,
                            'sent_wall': self.clock(), 'sent_mono': self.monotonic(),
                            'accepted': False, 'early': None}
            try:
                async with asyncio.timeout(self.request_timeout):
                    accepted = await self.app.invoke_live_read(function, request, self.topic, self.user)
                    if accepted != request:
                        raise FrameError('HTTP accepted ID does not match live query')
                    if self.failed or self.closed:
                        raise FrameError('Live connection lost; query outcome unknown')
                    self.pending['accepted'] = True
                    if self.pending['early'] is not None and not future.done():
                        future.set_result(self.pending['early'])
                    return await future
            except asyncio.CancelledError:
                raise
            except Exception:
                raise FrameError('Live query unverified; no retry was sent') from None
            finally:
                if not future.done():
                    future.cancel()
                elif not future.cancelled():
                    future.exception()  # consume disconnect errors even if HTTP failed first
                self.pending = None

    async def aclose(self):
        async with self.close_lock:
            if self.closed:
                return
            self.closed = True
            self._fail()
            # A shutdown racing executor startup must not leave a network loop
            # starting after disconnect/loop_stop have already returned.
            work = self.work
            if work is not None and work is not asyncio.current_task():
                try:
                    await asyncio.shield(work)
                except Exception:
                    pass
            client = self.client
            if client is not None:
                def stop():
                    try:
                        client.disconnect()
                    finally:
                        client.loop_stop()
                task = asyncio.create_task(asyncio.to_thread(stop))
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    await asyncio.shield(task)
                    raise
                except Exception:
                    pass
            if self.ready.done() and not self.ready.cancelled():
                self.ready.exception()

    async def __aexit__(self, *args):
        await self.aclose()
