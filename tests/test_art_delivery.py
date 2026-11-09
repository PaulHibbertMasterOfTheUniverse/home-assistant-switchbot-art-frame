import hashlib,io,unittest
from unittest.mock import AsyncMock,patch
from PIL import Image
from test_controller import manager,FrameError
from test_local_mode import Frame

def picture():
 out=io.BytesIO();Image.new('RGB',(40,30),'blue').save(out,'JPEG');return out.getvalue()

class Tests(unittest.IsolatedAsyncioTestCase):
 async def test_stored_image_needs_no_download(self):
  m=manager();f=Frame([7],'01000700');f.command=AsyncMock();m.local_connection=AsyncMock(return_value=f)
  await m.ensure_local_art(7);f.command.assert_not_awaited()
 async def test_failure_preserves_retry_copy(self):
  m=manager();m.local_key={'key':'private'};m.art_index=AsyncMock(return_value=7);m.data['last_art_upload']={'index':7};f=Frame([],'01000700');f.command=AsyncMock(return_value=bytes.fromhex('01353103'));m.local_connection=AsyncMock(return_value=f)
  f.upload_native=AsyncMock(side_effect=FrameError('Transfer interrupted'))
  with patch('asyncio.sleep',new=AsyncMock()):
   with self.assertRaises(FrameError):await m.upload(picture())
  f.show.assert_not_awaited();self.assertEqual(m.status,'error');self.assertEqual(m.data['last_art_upload']['index'],7)
 async def test_native_upload_requires_device_storage_confirmation(self):
  m=manager();f=Frame([],'01000700');f.upload_native=AsyncMock();m.local_connection=AsyncMock(return_value=f)
  with self.assertRaises(FrameError):await m.ensure_local_art(7,picture())
  f.show.assert_not_awaited()
 async def test_native_retry_rewrites_same_slot_without_cloud_download(self):
  m=manager();f=Frame([],'01000700');f.indices.side_effect=[[7],[7]];f.upload_native=AsyncMock();f.command=AsyncMock();m.local_connection=AsyncMock(return_value=f)
  await m.ensure_local_art(7,picture());await m.ensure_local_art(7,picture())
  self.assertEqual(f.upload_native.await_count,2);self.assertEqual([call.args[0] for call in f.upload_native.await_args_list],[7,7]);f.command.assert_not_awaited()
 async def test_native_timeout_reports_stage_without_selecting(self):
  m=manager();f=Frame([],'01000700');f.upload_native=AsyncMock(side_effect=TimeoutError());m.local_connection=AsyncMock(return_value=f)
  with self.assertRaisesRegex(FrameError,'Bluetooth image transfer failed after 3 attempts: TimeoutError'):
   await m.ensure_local_art(7,picture())
  f.show.assert_not_awaited()

if __name__=='__main__':unittest.main()

class OverrideTests(unittest.IsolatedAsyncioTestCase):
 async def test_active_baby_requires_explicit_override(self):
  m=manager(True);m.local_key={'key':'private'}
  with self.assertRaisesRegex(FrameError,'Confirm replacement'):await m.upload(picture())
 async def test_explicit_override_selects_art_without_changing_waterfall(self):
  m=manager(True);m.local_key={'key':'private'};m.art_index=AsyncMock(return_value=7);m.ensure_local_art=AsyncMock();f=Frame([7,8],'01000700');m.local_connection=AsyncMock(return_value=f)
  await m.upload(picture(),override_baby=True)
  self.assertTrue(m.hass.states.on);self.assertTrue(m.data['art_override']);self.assertFalse(m.desired());f.show.assert_awaited_once_with(7)
 async def test_failed_override_restores_baby_request(self):
  m=manager(True);m.local_key={'key':'private'};m.art_index=AsyncMock(side_effect=FrameError('failed'))
  with self.assertRaises(FrameError):await m.upload(picture(),override_baby=True)
  self.assertFalse(m.data['art_override']);self.assertTrue(m.desired())

class DownloadIdleTests(unittest.IsolatedAsyncioTestCase):
 async def test_cloud_download_must_finish_then_remain_quiet(self):
  from test_controller import Manager
  m=manager();f=Frame([7],'01000700')
  f.command=AsyncMock(side_effect=[bytes.fromhex('01353101')]*7+[bytes.fromhex('01353102')]*3)
  with patch('asyncio.sleep',new=AsyncMock()):await Manager.wait_native_idle(m,f)
  self.assertEqual(f.command.await_count,10)
  self.assertEqual(m.data['last_download_wait'],[{'seconds':0,'state':1},{'seconds':14,'state':2}])
 async def test_initial_idle_does_not_skip_cloud_settling_window(self):
  from test_controller import Manager
  m=manager();f=Frame([7],'01000700');f.command=AsyncMock(return_value=bytes.fromhex('01353102'))
  with patch('asyncio.sleep',new=AsyncMock()):await Manager.wait_native_idle(m,f)
  self.assertEqual(f.command.await_count,8)
 async def test_busy_timeout_never_authorizes_transfer(self):
  from test_controller import Manager
  m=manager();f=Frame([7],'01000700');f.command=AsyncMock(return_value=bytes.fromhex('01353101'))
  with patch('asyncio.sleep',new=AsyncMock()):
   with self.assertRaisesRegex(FrameError,'still downloading'):await Manager.wait_native_idle(m,f)
 async def test_unreadable_status_fails_closed(self):
  from test_controller import Manager
  m=manager();f=Frame([7],'01000700');f.command=AsyncMock(return_value=b'')
  with self.assertRaisesRegex(FrameError,'Could not confirm'):await Manager.wait_native_idle(m,f)
 async def test_upload_waits_before_writing_image_bytes(self):
  m=manager();f=Frame([7],'01000700');events=[]
  async def wait(frame):events.append('idle')
  async def write(*args):events.append('write')
  m.wait_native_idle=wait;f.upload_native=write;m.local_connection=AsyncMock(return_value=f)
  await m.ensure_local_art(7,picture());self.assertEqual(events,['idle','write'])

class ReconnectTests(unittest.IsolatedAsyncioTestCase):
 async def test_disconnected_transfer_restarts_same_slot_and_selects_only_after_success(self):
  m=manager();f=Frame([7],'01000700');f.upload_native=AsyncMock(side_effect=[ConnectionError('lost'),None]);m.local_connection=AsyncMock(return_value=f)
  with patch('asyncio.sleep',new=AsyncMock()):await m.ensure_local_art(7,picture())
  self.assertEqual([c.args[0] for c in f.upload_native.await_args_list],[7,7]);self.assertEqual(m.data['last_transfer']['attempts'],2);f.show.assert_not_awaited()
