"""Reusable configuration and artwork layout use the audience member's settings."""
import io,sys,unittest,tempfile
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch,Mock
from PIL import Image
sys.path.insert(0,str(Path(__file__).parents[1]))
from extras.frame_bin_reminder import Reminder,CONFIG_SCHEMA
class Tests(unittest.TestCase):
 def test_defaults_require_no_publisher_identity(self):
  result=CONFIG_SCHEMA({'frame_bin_reminder':{'frame_id':'my_frame','calendar_entity':'calendar.collections'}})['frame_bin_reminder']
  self.assertEqual(result['source'],'calendar');self.assertFalse(result['enabled']);self.assertEqual(result['reminder_weekday'],1)
 def test_bundled_artwork_uses_saved_layout_and_padding(self):
  for orientation in ('portrait','landscape'):
   for flip in (False,True):
    manager=NS(data={'layout':{'orientation':orientation,'flipped':flip}})
    obj=object.__new__(Reminder);obj._prepared_assets={};obj.config={'frame_id':'my_frame'};obj.hass=NS(data={'switchbot_frame_control':NS(select=lambda _:manager)})
    with patch('custom_components.switchbot_frame_control.native_image.cloud_assets',side_effect=lambda raw,*_: (raw,b'thumbnail',b'native')) as encoder:
     assets=obj.read_artwork('black')
     with Image.open(io.BytesIO(assets[0])) as image:
      self.assertEqual(image.size,(2560,1440));self.assertGreater(image.getpixel((0,0))[0],240)
     obj.read_artwork('black');encoder.assert_called_once()
 def test_household_artwork_directory_cannot_escape_configuration(self):
  with tempfile.TemporaryDirectory() as root:
   obj=object.__new__(Reminder);obj.config={'artwork_directory':'../outside'};obj.hass=NS(config=NS(config_dir=root,path=lambda name:str(Path(root)/name)))
   with self.assertRaises(ValueError):obj.artwork_assets('blue')
