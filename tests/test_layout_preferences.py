import unittest,types,json
from unittest.mock import AsyncMock
from test_controller import manager,FrameError
from test_multiframe import environment,Request
class Tests(unittest.IsolatedAsyncioTestCase):
 async def test_layout_is_saved_per_frame_and_returned_on_reload(self):
  a=manager();b=manager();a.frame_id='one';b.frame_id='two'
  await a.set_layout({'orientation':'portrait','flipped':True})
  self.assertEqual(a.store.saved[-1]['layout'],{'orientation':'portrait','flipped':True})
  self.assertNotIn('layout',b.data)
  env=environment();registry=env['FrameRegistry'](None,{'one':a,'two':b})
  rows=registry.descriptions()
  self.assertEqual(rows[0]['layout'],{'orientation':'portrait','flipped':True})
  self.assertEqual(rows[1]['layout'],{'orientation':'landscape','flipped':False})
 async def test_invalid_preferences_do_not_change_saved_layout(self):
  m=manager()
  for value in [None,{}, {'orientation':'sideways','flipped':False},{'orientation':'portrait','flipped':'false'}]:
   with self.assertRaises(FrameError):await m.set_layout(value)
  self.assertNotIn('layout',m.data);self.assertFalse(m.store.saved)
 async def test_preferences_endpoint_is_admin_only_and_targets_selected_frame(self):
  env=environment();a=manager();b=manager();a.set_layout=AsyncMock();b.set_layout=AsyncMock(return_value={'orientation':'landscape','flipped':True})
  view=env['FramesView'](env['FrameRegistry'](None,{'one':a,'two':b}))
  b.data={}
  payload={'frame_id':'two','expected_revision':0,'layout':{'orientation':'landscape','flipped':True}}
  self.assertEqual((await view.post(Request(payload,False))).status,403)
  a.set_layout.assert_not_awaited();b.set_layout.assert_not_awaited()
  result=await view.post(Request(payload));self.assertEqual(result.status,200)
  b.set_layout.assert_awaited_once_with(payload['layout'],expected_revision=0);a.set_layout.assert_not_awaited()
