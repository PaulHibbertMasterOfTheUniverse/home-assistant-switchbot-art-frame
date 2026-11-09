import asyncio,importlib.util,io,types,unittest
from pathlib import Path
from unittest.mock import AsyncMock
from PIL import Image
ROOT=Path(__file__).parent.parent/'custom_components/switchbot_frame_control'
def module(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'));value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
ble=module('local_ble');native=module('native_image')

class Tests(unittest.IsolatedAsyncioTestCase):
 def test_crc_matches_standard_modbus_vector(self):
  self.assertEqual(ble.crc16(b'123456789'),0x4b37)
 def test_native_half_buffers_and_rotation(self):
  image=Image.new('RGB',(1600,1200),'red');image.paste('blue',(800,0,1600,1200))
  out=io.BytesIO();image.save(out,'PNG');data=native.panel_bytes(out.getvalue())
  self.assertEqual(len(data),960000)
  # Landscape left half becomes the upper portrait half for this frame orientation.
  self.assertEqual(data[:240000],b'\x33'*240000)
  self.assertEqual(data[240000:480000],b'\x55'*240000)
  self.assertEqual(data[:480000],data[480000:])
 async def test_transfer_rejection_stops_before_finish(self):
  frame=object.__new__(ble.LocalFrame);frame.raw=AsyncMock(side_effect=[b'\x01',b'\x00',b'\x00',b'\x00']);frame.info=AsyncMock()
  frame.client=types.SimpleNamespace(services=types.SimpleNamespace(get_characteristic=lambda _:types.SimpleNamespace(max_write_without_response_size=244)))
  with self.assertRaisesRegex(RuntimeError,'data failed at 0/960000 bytes; packet size 244'):await frame.upload_native(7,b'\x11'*960000)
  self.assertEqual(frame.raw.await_count,4)
 async def test_gatt_chunks_respect_negotiated_size(self):
  frame=object.__new__(ble.LocalFrame);frame.q=asyncio.Queue();frame.q.put_nowait(b'\x01')
  frame.client=types.SimpleNamespace(services=types.SimpleNamespace(get_characteristic=lambda _:types.SimpleNamespace(max_write_without_response_size=180)),write_gatt_char=AsyncMock())
  data=b'x'*8192;self.assertEqual(await frame.raw(data),b'\x01')
  chunks=[c.args[1] for c in frame.client.write_gatt_char.await_args_list]
  self.assertEqual(b''.join(chunks),data);self.assertTrue(all(len(x)<=180 for x in chunks))
 async def test_bluez_mtu_is_acquired_before_larger_packets(self):
  frame=object.__new__(ble.LocalFrame);frame.q=asyncio.Queue();frame.q.put_nowait(b'\x01')
  backend=types.SimpleNamespace(_acquire_mtu=AsyncMock(),mtu_size=247)
  frame.client=types.SimpleNamespace(_backend=backend,services=types.SimpleNamespace(get_characteristic=lambda _:types.SimpleNamespace(max_write_without_response_size=20)),write_gatt_char=AsyncMock())
  self.assertEqual(await frame.transfer_size(),244);backend._acquire_mtu.assert_awaited_once()
  await frame.raw(b'x'*500)
  self.assertEqual([len(c.args[1]) for c in frame.client.write_gatt_char.await_args_list],[244,244,12])
 async def test_failed_mtu_negotiation_never_sends_oversize_data(self):
  frame=object.__new__(ble.LocalFrame)
  backend=types.SimpleNamespace(_acquire_mtu=AsyncMock(side_effect=TimeoutError()),mtu_size=247)
  frame.client=types.SimpleNamespace(_backend=backend,services=types.SimpleNamespace(get_characteristic=lambda _:types.SimpleNamespace(max_write_without_response_size=20)),write_gatt_char=AsyncMock())
  with self.assertRaisesRegex(RuntimeError,'negotiation failed: TimeoutError'):await frame.transfer_size()
  frame.client.write_gatt_char.assert_not_awaited()

class RetryTests(unittest.IsolatedAsyncioTestCase):
 async def test_rejected_block_is_retried_at_the_same_offset(self):
  frame=object.__new__(ble.LocalFrame);frame.info=AsyncMock()
  frame.client=types.SimpleNamespace(services=types.SimpleNamespace(get_characteristic=lambda _:types.SimpleNamespace(max_write_without_response_size=244)))
  calls=[];rejected=False
  async def reply(data):
   nonlocal rejected
   calls.append(data)
   if data[7]==1 and not rejected:rejected=True;return b'\x00'
   return b'\x01'
  frame.raw=reply
  await frame.upload_native(4092,b'\x11'*960000)
  frame.info.assert_not_awaited()
  blocks=[p for p in calls if p[7]==1]
  self.assertEqual(blocks[0],blocks[1]);self.assertEqual(len(blocks),119)
  self.assertEqual([p[7] for p in calls][-1],2)
