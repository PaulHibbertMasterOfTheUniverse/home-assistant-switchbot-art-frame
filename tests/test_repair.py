import json,tempfile,types,unittest
from pathlib import Path
from unittest.mock import AsyncMock
from test_controller import manager,ns,FrameError
from test_local_mode import Frame
ns['Path']=Path;ns['os']=__import__('os')
class Tests(unittest.IsolatedAsyncioTestCase):
 async def test_refresh_persists_rotated_key_without_losing_settings(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder,'frame_local_private.json');p.write_text(json.dumps({'device_id':'FRAME','communication_key':{'key':'old'},'other_setting':7}))
   m=manager();m.hass.config=types.SimpleNamespace(path=lambda name:str(Path(folder,name)));m.client.device='FRAME';m.client.communication_key=AsyncMock(return_value={'key':'a'*32,'keyId':'01'})
   await m.refresh_local_key();value=json.loads(p.read_text());self.assertEqual(value['other_setting'],7);self.assertEqual(m.local_key,value['communication_key']);self.assertEqual(p.stat().st_mode&0o777,0o600)
 async def test_refresh_does_not_replace_another_frames_settings(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder,'frame_local_private.json');p.write_text(json.dumps({'device_id':'OTHER','communication_key':{'key':'old'}}));before=p.read_bytes()
   m=manager();m.hass.config=types.SimpleNamespace(path=lambda name:str(Path(folder,name)));m.client.device='FRAME';m.client.communication_key=AsyncMock(return_value={'key':'a'*32,'keyId':'01'})
   with self.assertRaises(FrameError):await m.refresh_local_key()
   self.assertEqual(p.read_bytes(),before)
 async def test_repair_refreshes_playlist_without_changing_display(self):
  m=manager();m.data['baby_indices']=[8];m.refresh_local_key=AsyncMock();f=Frame([7,8,9],'01000800');m.local_connection=AsyncMock(return_value=f)
  await m.repair_connection();self.assertEqual(m.data['normal_indices'],[7,9]);f.show.assert_not_awaited();f.normal.assert_not_awaited();self.assertEqual(m.status,'connection_repaired')

class MissingBabyTests(unittest.IsolatedAsyncioTestCase):
 async def test_restores_only_missing_verified_baby_slot(self):
  from test_art_delivery import picture
  m=manager();m.data['baby_indices']=[8];m.refresh_local_key=AsyncMock();m.read_local_baby=AsyncMock(return_value=picture());m.client.catalogue.return_value=[{'imageIndex':8,'mainImageUrl':'saved-baby'}]
  f=Frame([7],'01000700');f.indices.side_effect=[[7],[7,8]];f.upload_native=AsyncMock();m.local_connection=AsyncMock(return_value=f)
  await m.repair_connection();self.assertEqual(f.upload_native.await_args.args[0],8);self.assertEqual(m.data['normal_indices'],[7]);f.show.assert_not_awaited()
 async def test_missing_local_source_never_overwrites_another_image(self):
  from test_art_delivery import picture
  m=manager();m.data['baby_indices']=[8];m.refresh_local_key=AsyncMock();m.read_local_baby=AsyncMock(return_value=picture());m.read_local_baby=AsyncMock(side_effect=FrameError('local baby source missing'))
  f=Frame([7],'01000700');f.upload_native=AsyncMock();m.local_connection=AsyncMock(return_value=f)
  with self.assertRaisesRegex(FrameError,'local baby source missing'):await m.repair_connection()
  f.upload_native.assert_not_awaited()
