import ast,unittest
from pathlib import Path
from unittest.mock import AsyncMock
ns={'LocalFrame':object}
p=Path(__file__).parent.parent/'custom_components/switchbot_frame_control/original_ble.py'
t=ast.parse(p.read_text());exec(compile(ast.Module(body=[n for n in t.body if isinstance(n,ast.ClassDef)],type_ignores=[]),str(p),'exec'),ns)
OriginalFrame=ns['OriginalFrame']
class Tests(unittest.IsolatedAsyncioTestCase):
 def frame(self):
  f=OriginalFrame();f.info=AsyncMock(return_value='011c0a01004b055cce43fd4b0000000000');f.command=AsyncMock(return_value=b'\x01');return f
 async def test_catalogue_uses_original_info_not_frame2_bitmap(self):
  f=self.frame();self.assertEqual(await f.indices(),[92,206,67,253,75]);f.command.assert_not_awaited()
 async def test_show_uses_one_byte_index(self):
  f=self.frame();await f.show(75);self.assertEqual([c.args[0] for c in f.command.call_args_list],['0f7a03004b00000000','0f7a024b'])
 async def test_playlist_uses_original_format_and_excludes_unlisted_images(self):
  f=self.frame();await f.normal([92,206]);f.command.assert_awaited_once_with('0f7a0301001e5cce')
 async def test_missing_or_large_ids_cannot_issue_commands(self):
  for index in (4093,0,240,True):
   f=self.frame()
   with self.assertRaises(ValueError):await f.show(index)
   f.command.assert_not_awaited()
 async def test_unverified_upload_fails_closed(self):
  f=self.frame()
  with self.assertRaisesRegex(RuntimeError,'no cloud fallback'):await f.upload_native(240,b'x')
  f.command.assert_not_awaited()
