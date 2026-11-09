import types,unittest
from unittest.mock import AsyncMock
from test_controller import manager,FrameError,AppClient,ns
from test_fully_local import setup,picture

class Tests(unittest.IsolatedAsyncioTestCase):
 async def test_mode_persists_per_frame_and_no_network_or_bluetooth_on_toggle(self):
  a=manager();b=manager();a.local_key={'key':'private'};b.local_key={'key':'private'}
  a.local_connection=AsyncMock();a.client.authenticate=AsyncMock()
  await a.set_connection_mode('wifi')
  self.assertEqual(a.connection_mode(),'wifi');self.assertEqual(b.connection_mode(),'local')
  a.local_connection.assert_not_awaited();a.client.authenticate.assert_not_awaited()
 async def test_wifi_mode_never_calls_bluetooth(self):
  m=manager();m.data['connection_mode']='wifi';m.local_connection=AsyncMock(side_effect=AssertionError('Bluetooth forbidden'))
  m.cloud_art=AsyncMock(return_value=91);m.client.download=AsyncMock();m.client.select_downloaded=AsyncMock(return_value=True)
  result=await m.upload(picture());self.assertFalse(result['sent']);self.assertTrue(result['accepted']);self.assertTrue(result['cloud_upload'])
  m.local_connection.assert_not_awaited();m.client.download.assert_awaited_once_with(91,'frame2')
 async def test_original_local_upload_is_rejected_without_cloud(self):
  m=manager();m.config['model']='frame1';m.data['connection_mode']='local';m.cloud_art=AsyncMock()
  with self.assertRaisesRegex(FrameError,'original frame require'):await m.upload(picture())
  m.cloud_art.assert_not_awaited()
 async def test_original_has_one_byte_mode_and_rejects_frame2_ids(self):
  m=manager();m.config['model']='frame1'
  self.assertTrue(m.mode_matches('01004b000000',75));self.assertFalse(m.mode_matches('01004c000000',75))
  with self.assertRaises(FrameError):m.check_index(4093)
 async def test_hybrid_uses_cloud_only_after_connection_preflight_failure(self):
  m=manager();m.local_key={'key':'private'};m.data['connection_mode']='hybrid'
  m.local_connection=AsyncMock(side_effect=FrameError('not reachable'));m.deliver_cloud_art=AsyncMock(return_value={'accepted':True})
  self.assertEqual(await m.upload(picture()),{'accepted':True});m.deliver_cloud_art.assert_awaited_once()
 async def test_failed_partial_local_transfer_does_not_trigger_cloud_fallback(self):
  m,f=setup(False);m.data['connection_mode']='hybrid';m.deliver_cloud_art=AsyncMock()
  m.ensure_local_art=AsyncMock(side_effect=FrameError('uncertain partial transfer'))
  with self.assertRaises(FrameError):await m.upload(picture())
  m.deliver_cloud_art.assert_not_awaited()
 async def test_wifi_notification_and_restore_never_connect_ble(self):
  m=manager();m.data.update(connection_mode='wifi',manual_baby=True,baby_indices=[75],normal_indices=[92,206])
  m.config['model']='frame1';m.local_connection=AsyncMock(side_effect=AssertionError('BLE forbidden'))
  await m.reconcile();m.client.show.assert_awaited_once_with(75,'frame1')
  m.data['manual_baby']=False;await m.reconcile();m.client.normal.assert_awaited_once_with([92,206],'frame1');m.local_connection.assert_not_awaited()
 async def test_uncertain_registration_cannot_add_duplicate(self):
  m=manager();m.data['pending_cloud_registration']={'sha256':'uncertain'};m.client.upload_assets=AsyncMock()
  with self.assertRaisesRegex(FrameError,'uncertain'):await m.cloud_art(picture())
  m.client.upload_assets.assert_not_awaited()
 async def test_cloud_retry_reuses_existing_index(self):
  import hashlib
  m=manager();m.data['cloud_art_uploads']={hashlib.sha256(picture()).hexdigest():91};m.client.upload_assets=AsyncMock()
  self.assertEqual(await m.cloud_art(picture()),91);m.client.upload_assets.assert_not_awaited()
 async def test_original_cloud_commands_use_original_function_ids(self):
  c=AppClient(None,{'session':{'headers':{}},'device_id':'D','group_id':'G'});c.invoke=AsyncMock()
  await c.show(75,'frame1');await c.normal([75,92],'frame1');await c.download(91,'frame1')
  self.assertEqual([x.args[0] for x in c.invoke.await_args_list],[9604,9602,9605,9609,9601])
 def test_cloud_native_asset_dimensions(self):
  import importlib.util
  from pathlib import Path
  spec=importlib.util.spec_from_file_location('native',Path(__file__).parent.parent/'custom_components/switchbot_frame_control/native_image.py');n=importlib.util.module_from_spec(spec);spec.loader.exec_module(n)
  self.assertEqual(len(n.cloud_assets(picture(),'frame1')[2]),192000)
  self.assertEqual(len(n.cloud_assets(picture(),'frame2')[2]),960000)
 async def test_cloud_slot_collision_does_not_overwrite_local_art(self):
  m=manager();m.data['local_art_uploads']={'local':4093};m.cloud_art=AsyncMock(return_value=4093);m.client.download=AsyncMock()
  with self.assertRaisesRegex(FrameError,'overlaps'):await m.deliver_cloud_art(picture())
  m.client.download.assert_not_awaited()
 async def test_rejected_cloud_session_renews_once_before_retry(self):
  class Response:
   status=200
   def __init__(self,code):self.code=code
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   async def json(self):return {'resultCode':self.code,'data':{'ok':True}}
  responses=iter([Response(191),Response(100)])
  c=AppClient(types.SimpleNamespace(post=lambda *a,**k:next(responses)),{'session':{'headers':{}},'device_id':'D','group_id':'G'})
  c.authenticate=AsyncMock()
  self.assertEqual(await c.post('/test',{}),{'ok':True})
  self.assertEqual(sum(call.kwargs.get('force',False) for call in c.authenticate.await_args_list),1)
 async def test_repeated_cloud_session_rejection_does_not_loop(self):
  class Response:
   status=200
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   async def json(self):return {'resultCode':191}
  c=AppClient(types.SimpleNamespace(post=lambda *a,**k:Response()),{'session':{'headers':{}},'device_id':'D','group_id':'G'});c.authenticate=AsyncMock()
  with self.assertRaisesRegex(FrameError,'191'):await c.post('/test',{})
  self.assertEqual(sum(call.kwargs.get('force',False) for call in c.authenticate.await_args_list),1)

 async def test_frame2_wifi_selection_does_not_use_original_storage_field(self):
  c=AppClient(None,{'session':{'headers':{}},'device_id':'D','group_id':'G'});c.show=AsyncMock();c.reported_state=AsyncMock()
  self.assertFalse(await c.select_downloaded(91,'frame2'));c.show.assert_awaited_once_with(91,'frame2');c.reported_state.assert_not_awaited()
 async def test_wifi_stored_selection_never_calls_ble(self):
  m=manager();m.data['connection_mode']='wifi';m.local_connection=AsyncMock(side_effect=AssertionError('BLE forbidden'))
  await m.select_image(75);m.client.show.assert_awaited_once_with(75,'frame2');m.local_connection.assert_not_awaited()
 async def test_reconcile_recovers_exact_pending_filename(self):
  m=manager();m.data['pending_cloud_registration']={'sha256':'digest','files':['exact.jpg']};m.client.catalogue=AsyncMock(return_value=[{'mainImageUrl':'https://example.invalid/exact.jpg','imageIndex':91}])
  await m.reconcile_registration();self.assertEqual(m.data['cloud_art_uploads']['digest'],91);self.assertNotIn('pending_cloud_registration',m.data)
 async def test_unknown_registration_requires_operator_confirmation(self):
  m=manager();m.data['pending_cloud_registration']={'sha256':'digest','files':['missing.jpg']}
  with self.assertRaisesRegex(FrameError,'uncertain'):await m.reconcile_registration()
  self.assertIn('pending_cloud_registration',m.data)
  await m.reconcile_registration(True);self.assertNotIn('pending_cloud_registration',m.data)

 async def test_frame2_sync_matches_captured_app_list_command(self):
  c=AppClient(None,{'session':{'headers':{}},'device_id':'D','group_id':'G'});c.invoke=AsyncMock();await c.download(4115,'frame2');c.invoke.assert_awaited_once_with(9623,{'0':1,'1':[4115]})
