import hashlib,types,unittest
from unittest.mock import AsyncMock
from test_controller import manager,FrameError
from test_local_mode import Frame
from test_art_delivery import picture

def setup(on=False,indices=(7,8),mode='0100fd0f'):
 m=manager(on);m.local_key={'key':'private'}
 f=Frame(list(indices),mode);f.upload_native=AsyncMock();f.command=AsyncMock(return_value=bytes.fromhex('01353102'))
 m.local_connection=AsyncMock(return_value=f)
 for name in ['catalogue','show','normal','remove','communication_key']:
  setattr(m.client,name,AsyncMock(side_effect=AssertionError('SwitchBot cloud forbidden: '+name)))
 m.read_image=AsyncMock(side_effect=AssertionError('HTTP image download forbidden'))
 return m,f
class Tests(unittest.IsolatedAsyncioTestCase):
 async def test_new_slot_comes_only_from_device_and_is_reserved_before_transfer(self):
  m,f=setup(indices=(4093,4092,8));i=await m.art_index(picture())
  self.assertEqual(i,4091);self.assertEqual(m.data['local_art_uploads'][hashlib.sha256(picture()).hexdigest()],4091)
  f.upload_native.assert_not_awaited();self.assertTrue(m.store.saved)
 async def test_retry_reuses_reserved_slot_even_if_first_transfer_did_not_finish(self):
  m,f=setup();i=await m.art_index(picture());self.assertEqual(await m.art_index(picture()),i)
  self.assertEqual(len(m.data['local_art_uploads']),1)
 async def test_previous_successful_cloud_slot_can_be_reused_without_cloud_lookup(self):
  m,f=setup();m.data['last_art_upload']={'sha256':hashlib.sha256(picture()).hexdigest(),'index':7}
  self.assertEqual(await m.art_index(picture()),7)
 async def test_full_upload_works_when_every_cloud_method_raises(self):
  m,f=setup(indices=(7,8,4093));f.indices.side_effect=[[7,8],[7,8,4093],[7,8,4093]]
  r=await m.upload(picture());self.assertTrue(r['sent']);self.assertFalse(r['cloud_upload']);self.assertEqual(r['transport'],'Bluetooth')
  f.upload_native.assert_awaited_once();f.show.assert_awaited_once_with(4093)
 async def test_storage_full_never_overwrites(self):
  m,f=setup(indices=range(1,4094))
  with self.assertRaisesRegex(FrameError,'No unused'):await m.art_index(picture())
  f.upload_native.assert_not_awaited();f.show.assert_not_awaited()
 async def test_no_bluetooth_key_never_falls_back_to_cloud(self):
  m,f=setup();m.local_key=None
  with self.assertRaisesRegex(FrameError,'no cloud upload'):await m.upload(picture())
  f.upload_native.assert_not_awaited()
 async def test_missing_source_never_triggers_a_cloud_download(self):
  m,f=setup(indices=())
  with self.assertRaisesRegex(FrameError,'no cloud download'):await m.ensure_local_art(9)
  f.command.assert_not_awaited()
 async def test_baby_on_off_only_uses_local_device(self):
  m,f=setup(True,indices=(7,8),mode='01000800');m.data['baby_indices']=[8]
  await m.reconcile();self.assertEqual(m.status,'baby_selected');f.show.assert_awaited_once_with(8)
  m.hass.states.on=False;f.mode_info.return_value='0101001e000005a07f01'
  await m.reconcile();self.assertEqual(m.status,'normal');f.normal.assert_awaited_once_with([7])
 async def test_initial_baby_provision_uses_local_source_and_local_slot(self):
  m,f=setup(True,indices=(7,4093));m.read_local_baby=AsyncMock(return_value=picture());m.art_index=AsyncMock(return_value=4093);f.mode_info.return_value='0100fd0f'
  await m.reconcile();self.assertEqual(m.status,'baby_selected');self.assertEqual(m.data['baby_indices'],[4093]);f.upload_native.assert_awaited_once()
