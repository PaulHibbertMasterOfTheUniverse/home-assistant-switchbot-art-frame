import io,json,types,unittest
from unittest.mock import AsyncMock
from PIL import Image
from test_controller import ns,manager,FrameError
from test_multiframe import environment,Request
prepare=ns['prepare_source']
class Tests(unittest.IsolatedAsyncioTestCase):
 def test_large_camera_photo_and_over_8mb_source_are_bounded(self):
  out=io.BytesIO();Image.new('RGB',(8000,6000),'blue').save(out,'JPEG')
  raw=out.getvalue()+b'\0'*(9*1024*1024)
  result=prepare(raw,2560)
  with Image.open(io.BytesIO(result)) as image:self.assertLessEqual(max(image.size),2560);self.assertEqual(image.size[0]*3,image.size[1]*4)
  self.assertLess(len(result),8*1024*1024)
 def test_exif_orientation_is_applied_before_preview(self):
  out=io.BytesIO();im=Image.new('RGB',(120,80),'red');exif=im.getexif();exif[274]=6;im.save(out,'JPEG',exif=exif)
  with Image.open(io.BytesIO(prepare(out.getvalue(),800))) as result:self.assertEqual(result.size,(80,120))
 def test_invalid_picture_is_rejected(self):
  with self.assertRaises(FrameError):prepare(b'not a picture',1600)
 async def test_endpoint_is_admin_only_and_does_not_upload_to_frame(self):
  env=environment();m=manager();m.config['model']='frame1';m.config['panel_size']='31.5';m.upload=AsyncMock()
  class Content:
   async def iter_chunked(self,size):yield b'image'
  request=Request({},False);request.query={'frame_id':'one'};request.content=Content();request.content_length=5
  view=env['PrepareView'](env['FrameRegistry'](None,{'one':m}));self.assertEqual((await view.post(request)).status,403);m.upload.assert_not_awaited()
 async def test_endpoint_prepares_only_for_selected_frame(self):
  env=environment();m=manager();m.config.update(model='frame1',panel_size='31.5');m.upload=AsyncMock();raw=io.BytesIO();Image.new('RGB',(3000,2000),'green').save(raw,'JPEG')
  class Content:
   async def iter_chunked(self,size):
    value=raw.getvalue()
    for start in range(0,len(value),size):yield value[start:start+size]
  request=Request({});request.query={'frame_id':'one'};request.content=Content();request.content_length=len(raw.getvalue())
  view=env['PrepareView'](env['FrameRegistry'](None,{'one':m}));response=await view.post(request)
  self.assertEqual(response.status,200);self.assertEqual(json.loads(response.text)['bound'],2560);m.upload.assert_not_awaited()
