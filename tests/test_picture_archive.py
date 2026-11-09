import json,os,tempfile,types,unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
from test_controller import manager,ns,FrameError
from test_fully_local import picture
from test_multiframe import environment,Request
class Tests(unittest.IsolatedAsyncioTestCase):
 async def test_private_backup_is_verified_and_recoverable(self):
  with tempfile.TemporaryDirectory() as folder,patch.dict(ns,{'Path':Path,'os':os}):
   m=manager();m.hass.config=types.SimpleNamespace(path=lambda *parts:str(Path(folder).joinpath(*parts)));m.read_image=AsyncMock(return_value=picture())
   await m.archive_cloud_art(7,[{'imageIndex':7,'mainImageUrl':'https://example.invalid/source.jpg'}])
   item=m.data['last_archived_art'];path=Path(folder,'frame_art_archive',m.frame_id,item['name'])
   self.assertEqual(path.stat().st_mode&0o777,0o600);self.assertEqual(await m.archived_art(),picture())
   path.write_bytes(b'corrupt')
   with self.assertRaisesRegex(FrameError,'verification'):await m.archived_art()
 async def test_missing_source_refuses_to_remove_picture(self):
  m=manager();m.read_image=AsyncMock()
  with self.assertRaisesRegex(FrameError,'nothing was removed'):await m.archive_cloud_art(7,[{'imageIndex':7}])
  m.read_image.assert_not_awaited()
 async def test_backup_endpoint_is_admin_only_and_frame_scoped(self):
  env=environment();a=types.SimpleNamespace(frame_id='one',archived_art=AsyncMock(return_value=b'a'));b=types.SimpleNamespace(frame_id='two',archived_art=AsyncMock(return_value=b'b'))
  view=env['ArchiveView'](env['FrameRegistry'](None,{'one':a,'two':b}))
  self.assertEqual((await view.post(Request({'frame_id':'two'},False))).status,403);b.archived_art.assert_not_awaited()
  result=await view.post(Request({'frame_id':'two'}));self.assertEqual(json.loads(result.text)['image'],'Yg==');a.archived_art.assert_not_awaited()
  self.assertEqual((await view.post(Request({'frame_id':'missing'}))).status,400)
 async def test_current_backup_does_not_select_upload_or_delete(self):
  m=manager();m.config['model']='frame1';m.client.reported_state=AsyncMock(return_value={'9601':{'value':7}});m.archive_cloud_art=AsyncMock()
  await m.backup_current_picture();m.archive_cloud_art.assert_awaited_once_with(7,m.client.catalogue.return_value)
  m.client.show.assert_not_awaited();m.client.remove.assert_not_awaited();self.assertEqual(m.status,'picture_backed_up')
