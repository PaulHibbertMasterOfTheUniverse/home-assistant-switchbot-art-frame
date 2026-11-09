import sys,types,unittest
from unittest.mock import AsyncMock,patch
from test_controller import manager,ns,FrameError

class RecoveryTests(unittest.IsolatedAsyncioTestCase):
 async def test_wifi_repair_forces_login_without_any_local_key(self):
  m=manager();m.data['connection_mode']='wifi';m.client.authenticate=AsyncMock();m.refresh_local_key=AsyncMock(side_effect=AssertionError('No local key in Wi-Fi mode'))
  await m.repair_connection()
  m.client.authenticate.assert_awaited_once_with(force=True);m.refresh_local_key.assert_not_awaited();self.assertEqual(m.status,'connection_repaired')
 async def run_registration(self,error,items):
  m=manager();m.client.upload_assets=AsyncMock(return_value=['new.jpg','thumb.jpg','data.bin']);m.client.register_image=AsyncMock(side_effect=error);m.client.catalogue=AsyncMock(return_value=items)
  fake=types.SimpleNamespace(cloud_assets=lambda *args:(b'main',b'thumb',b'data'))
  with patch.dict(ns,{'__package__':'cloud_test'}),patch.dict(sys.modules,{'cloud_test.native_image':fake}):
   try:result=await m.cloud_art(b'photo')
   except FrameError as caught:result=caught
  return m,result
 async def test_explicit_rejection_with_no_catalogue_match_releases_lock(self):
  e=FrameError('rejected191');e.result_code=191
  m,result=await self.run_registration(e,[{'imageIndex':4,'mainImageUrl':'https://example.invalid/old.jpg'}])
  self.assertIs(result,e);self.assertNotIn('pending_cloud_registration',m.data)
 async def test_timeout_keeps_lock_even_if_no_match_yet(self):
  e=FrameError('timed out')
  m,result=await self.run_registration(e,[])
  self.assertIs(result,e);self.assertIn('pending_cloud_registration',m.data);m.client.catalogue.assert_not_awaited()
 async def test_rejection_recovers_exact_existing_entry_without_duplicate(self):
  e=FrameError('rejected191');e.result_code=191
  m,result=await self.run_registration(e,[{'imageIndex':14,'mainImageUrl':'https://example.invalid/new.jpg'}])
  self.assertEqual(result,14);self.assertNotIn('pending_cloud_registration',m.data);m.client.register_image.assert_awaited_once()
 async def test_ambiguous_catalogue_keeps_lock(self):
  e=FrameError('rejected191');e.result_code=191
  m,result=await self.run_registration(e,[{'imageIndex':i,'mainImageUrl':'https://example.invalid/new.jpg'} for i in (14,15)])
  self.assertIs(result,e);self.assertIn('pending_cloud_registration',m.data)
 async def test_error_does_not_advertise_old_success(self):
  m=manager();m.last_action='Previous download accepted';m.last_storage_verified=True
  await m.report_failure(FrameError('New upload rejected'))
  self.assertEqual(m.last_action,'Operation failed');self.assertFalse(m.last_storage_verified);self.assertEqual(m.error,'New upload rejected')

class RegistrationResponseTests(unittest.IsolatedAsyncioTestCase):
 async def test_capacity_rejection_does_not_force_login_or_repeat_save(self):
  from test_controller import AppClient
  class Response:
   status=200
   async def __aenter__(self):return self
   async def __aexit__(self,*args):pass
   async def json(self):return {'resultCode':191,'message':'save image failed'}
  calls=[]
  def post(*args,**kwargs):calls.append(args);return Response()
  c=AppClient(types.SimpleNamespace(post=post),{'session':{'headers':{}},'device_id':'D','group_id':'G'});c.authenticate=AsyncMock()
  with self.assertRaises(FrameError) as caught:await c.post('/device/artframe/api/v1/images/save',{})
  self.assertEqual(caught.exception.result_code,191);self.assertEqual(len(calls),1)
  self.assertFalse(any(call.kwargs.get('force') for call in c.authenticate.await_args_list))
