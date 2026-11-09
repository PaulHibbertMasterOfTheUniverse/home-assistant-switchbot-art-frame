"""Reference checks for the recovered 31.5-inch app colour profile."""
import importlib.util,unittest
from pathlib import Path
from PIL import Image
spec=importlib.util.spec_from_file_location('native_colour',Path(__file__).parent.parent/'custom_components/switchbot_frame_control/native_image.py');n=importlib.util.module_from_spec(spec);spec.loader.exec_module(n)
class VendorColourTests(unittest.TestCase):
 def test_neutral_blackpoint_and_contrast(self):
  im=Image.new('RGB',(4,1));im.putdata([(0,0,0),(128,128,128),(240,240,240),(255,255,255)])
  self.assertEqual(list(n.vendor_adjust(im).getdata()),[(0,0,0),(118,118,118),(242,242,242),(255,255,255)])
 def test_calibrated_six_ink_palette(self):
  self.assertEqual(n.PALETTE,((0,0,0),(255,255,255),(255,255,0),(159,0,0),(0,0,255),(0,143,0)))
  for i,c in enumerate(n.PALETTE):
   self.assertEqual(n.stucki(Image.new('RGB',(4,4),c),indexed=True).tobytes(),bytes([i])*16)
 def test_small_picture_is_deterministic_bounded_and_has_no_padded_palette(self):
  im=Image.new('RGB',(7,5));im.putdata([((i*31)%256,(i*67)%256,(i*13)%256) for i in range(35)])
  a=n.stucki(n.vendor_adjust(im),indexed=True).tobytes()
  self.assertEqual(len(a),35);self.assertTrue(set(a)<=set(range(6)))
  self.assertEqual(a,n.stucki(n.vendor_adjust(im),indexed=True).tobytes())
 def test_colour_adjustment_preserves_bounds(self):
  im=Image.new('RGB',(3,1));im.putdata([(255,0,0),(0,255,0),(0,0,255)])
  self.assertEqual(list(n.vendor_adjust(im).getdata()),[(255,0,0),(0,255,0),(0,0,255)])
if __name__=='__main__':unittest.main()
