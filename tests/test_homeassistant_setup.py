"""Real Home Assistant API smoke tests, with all external device calls mocked."""
import asyncio,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
try:
 from homeassistant.core import HomeAssistant
 from homeassistant.config_entries import ConfigEntries,ConfigEntry
except ImportError:
 HomeAssistant=None
sys.path.insert(0,str(Path(__file__).parent.parent))

@unittest.skipIf(HomeAssistant is None,'Install Home Assistant to run real API smoke tests')
class HomeAssistantSetupTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  from custom_components.switchbot_frame_control import config_flow
  self.module=config_flow;self.tmp=tempfile.TemporaryDirectory();self.hass=HomeAssistant(self.tmp.name)
  self.hass.config_entries=ConfigEntries(self.hass,{})
 async def asyncTearDown(self):
  await self.hass.async_stop(force=True);self.tmp.cleanup()
 async def test_flow_discovers_frame_and_discards_cloud_login_for_local_entry(self):
  flow=self.module.ConfigFlow();flow.hass=self.hass;flow.flow_id='test-flow';flow.context={'source':'user'}
  frame={'device_id':'AABBCCDDEE01','group_id':'example-group','model':'frame2','name':'Example frame'}
  seed={'session':{'headers':{'authorization':'fake-session'}},'region':'eu','login':{'username':'demo@invalid.example','password':'secret'},'login_template':{}}
  with patch.object(self.module,'discover_account',AsyncMock(return_value=(seed,[frame]))),patch.object(self.module,'async_get_clientsession',return_value=None):
   result=await flow.async_step_user({'username':'demo@invalid.example','password':'secret'})
  self.assertEqual(result['step_id'],'frame')
  result=await flow.async_step_frame({'device_id':frame['device_id']});self.assertEqual(result['step_id'],'details')
  client=SimpleNamespace(communication_key=AsyncMock(return_value={'key':'00'*16,'keyId':'01'}))
  with patch.object(self.module,'AppClient',return_value=client),patch.object(self.module,'async_get_clientsession',return_value=None):
   result=await flow.async_step_details({'name':'Example frame','panel_size':'13.3','connection_mode':'local','keep_cloud_login':False,'use_example_image':False})
  self.assertEqual(result['type'],'create_entry');self.assertNotIn('login',result['data']['seed'])
  self.assertEqual(result['data']['seed']['session']['headers'],{})
  self.assertNotIn('credentials_file',result['data']['settings'])
  self.assertEqual(result['data']['local']['device_id'],frame['device_id'])
 async def test_rejects_unsupported_frame2_size_and_missing_cloud_login(self):
  with self.assertRaises(Exception):self.module.validate_details({'panel_size':'31.5','connection_mode':'local'},'frame2')
  with self.assertRaises(Exception):self.module.validate_details({'panel_size':'13.3','connection_mode':'wifi','keep_cloud_login':False},'frame2')
 async def test_entry_setup_and_unload_do_not_upload_or_select(self):
  import custom_components.switchbot_frame_control as integration
  from homeassistant.helpers.storage import Store
  entry=ConfigEntry(version=1,minor_version=1,domain='switchbot_frame_control',title='Example',source='user',unique_id='AABBCCDDEE01',options={},discovery_keys={},subentries_data=[],data={
   'settings':{'id':'example_frame','name':'Example','device_id':'AABBCCDDEE01','model':'frame2','panel_size':'13.3','connection_mode':'local','local_key_file':'unused.json'},
   'seed':{'device_id':'AABBCCDDEE01','group_id':'','session':{'headers':{}}},
   'local':{'device_id':'AABBCCDDEE01','communication_key':{'key':'00'*16,'keyId':'01'}}})
  self.hass.data['switchbot_frame_control']=integration.FrameRegistry(self.hass,{})
  with patch.object(integration,'async_get_clientsession',return_value=None),patch.object(Store,'async_load',AsyncMock(return_value=None)):
   await integration.async_setup_entry(self.hass,entry)
  manager=entry.runtime_data
  self.assertEqual(manager.local_key['key'],'00'*16)
  self.assertEqual(self.hass.states.get(manager.entity_id).state,'ready')
  self.assertFalse(manager.tasks)
  await integration.async_unload_entry(self.hass,entry)
  self.assertEqual(self.hass.data['switchbot_frame_control'].managers,{})
  self.assertIsNone(self.hass.states.get(manager.entity_id))

 async def test_empty_setup_registers_endpoints_services_and_bundled_card(self):
  import custom_components.switchbot_frame_control as integration
  registered=[]
  http=SimpleNamespace(register_view=registered.append,async_register_static_paths=AsyncMock())
  with patch.object(self.hass,'http',http,create=True),patch('homeassistant.components.frontend.add_extra_js_url') as add_js:
   self.assertTrue(await integration.async_setup(self.hass,{}))
  self.assertEqual(len(registered),5)
  self.assertTrue(self.hass.services.has_service('switchbot_frame_control','select_image'))
  self.assertTrue(self.hass.services.has_service('switchbot_frame_control','show_baby'))
  http.async_register_static_paths.assert_awaited_once();add_js.assert_called_once()
