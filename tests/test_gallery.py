"""Private gallery persistence, admin access and destination routing."""
import base64,io,tempfile,unittest,sys,json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from PIL import Image
sys.path.insert(0,str(Path(__file__).parents[1]))
from custom_components.switchbot_frame_control.gallery import Gallery,GalleryView,ImageView,prepare_transport
class Tests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.hass=NS(config=NS(config_dir=self.tmp.name,path=lambda p:str(Path(self.tmp.name)/p)),async_add_executor_job=AsyncMock(side_effect=lambda fn,*a:fn(*a)))
  self.gallery=Gallery(self.hass,{'directory':'gallery'})
 async def asyncTearDown(self):self.tmp.cleanup()
 def raw(self):
  b=io.BytesIO();Image.new('RGB',(120,80),'red').save(b,'PNG');return b.getvalue()
 async def test_identical_bytes_reuse_one_saved_id(self):
  first=self.gallery.save_image(self.raw(),'First');second=self.gallery.save_image(self.raw(),'Second')
  self.assertEqual(first,second);self.assertEqual(len(self.gallery.list_images()),1);self.assertEqual(self.gallery.read_index()[first]['name'],'Second')
 async def test_traversal_and_outside_directory_rejected(self):
  for value in ('../secrets','/etc/passwd','a/b','UPPER'):
   with self.assertRaises(ValueError):self.gallery.path(value)
  with self.assertRaises(ValueError):Gallery(self.hass,{'directory':'../outside'})
 async def test_endpoints_reject_non_admin_before_reading(self):
  req={'hass_user':NS(is_admin=False)}
  self.assertEqual((await GalleryView(self.gallery).get(req)).status,403)
  self.assertEqual((await ImageView(self.gallery).get(req,'anything')).status,403)
 async def test_send_routes_only_requested_frame_and_override(self):
  image=self.gallery.save_image(self.raw(),'Example');manager=NS(data={'layout':{'orientation':'portrait','flipped':True}},config={'panel_size':'13.3'},upload=AsyncMock(return_value={'sent':True}))
  calls=[]
  def select(fid):calls.append(fid);return manager
  self.hass.data={'switchbot_frame_control':NS(select=select)}
  await self.gallery.send(image,'second_frame',True)
  self.assertEqual(calls,['second_frame']);self.assertTrue(manager.upload.call_args.kwargs['override_baby'])
  with Image.open(io.BytesIO(manager.upload.call_args.args[0])) as im:self.assertEqual(im.size,(1600,1200))
 async def test_example_import_opt_in_and_repeat_safe(self):
  self.assertEqual(self.gallery.list_images(),[])
  first=self.gallery.import_bin_artwork();second=self.gallery.import_bin_artwork()
  self.assertEqual(first,second);self.assertEqual(set(first),{'blue','black','none'});self.assertEqual(len(self.gallery.list_images()),3)
 async def test_saved_copy_has_no_image_metadata(self):
  key=self.gallery.save_image(self.raw(),'Example')
  with Image.open(self.gallery.path(key)) as im:self.assertFalse(im.getexif());self.assertNotIn('exif',im.info)
