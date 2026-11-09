import hashlib,io,unittest
from PIL import Image
from test_controller import native
from test_fully_local import picture
from test_multiframe import environment
class Tests(unittest.TestCase):
 def test_large_scanlines_match_captured_switchbot_app_reference(self):
  # Expected digest was produced independently by running changeBinData31
  # from app-image-conversion.js against this deterministic packed input.
  packed=bytes((i*13+((i>>5)*7))&255 for i in range(1843200))
  self.assertEqual(hashlib.sha256(native['original_large_scanlines'](packed)).hexdigest(),'74cad8ab901b1b28407b018d7766d5cfc663942ea22b624c190de6a075fd83f2')
 def test_house_cloud_assets_use_their_native_dimensions_and_lengths(self):
  for size,dimensions,length in [('13.3',(1600,1200),960000),('31.5',(2560,1440),1843200)]:
   main,thumb,buffer=native['cloud_assets'](picture(),'frame1',size)
   with Image.open(io.BytesIO(main)) as im:self.assertEqual(im.size,dimensions)
   self.assertEqual(len(buffer),length)
 def test_four_frame_destination_profiles_are_separate(self):
  env=environment();configs=env['frame_configs']({'frames':[
   {'id':fid,'device_id':fid,'model':model,'panel_size':size,'connection_mode':mode,'local_key_file':fid+'.json'}
   for fid,model,size,mode in [('main_frame','frame2','13.3','local'),('small_frame','frame1','7.3','hybrid'),('large_frame','frame1','31.5','wifi'),('medium_frame','frame1','13.3','wifi')]]})
  self.assertEqual([(x['id'],x['panel_size'],x['connection_mode']) for x in configs[-2:]],[('large_frame','31.5','wifi'),('medium_frame','13.3','wifi')])
 def test_frame2_does_not_accept_unvalidated_size(self):
  with self.assertRaises(ValueError):native['cloud_assets'](picture(),'frame2','31.5')
