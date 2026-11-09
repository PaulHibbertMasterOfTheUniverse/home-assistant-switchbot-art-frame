"""Account discovery never relies on a developer's captured identities."""
import importlib,sys,types,unittest
from pathlib import Path
from unittest.mock import AsyncMock
ROOT=Path(__file__).parent.parent/'custom_components/switchbot_frame_control'
pkg=types.ModuleType('public_onboarding');pkg.__path__=[str(ROOT)];sys.modules['public_onboarding']=pkg
setup=importlib.import_module('public_onboarding.onboarding')
protocol=importlib.import_module('public_onboarding.protocol')
class Response:
 status=200
 def __init__(self,value):self.value=value
 async def __aenter__(self):return self
 async def __aexit__(self,*args):pass
 async def json(self):return self.value
class HTTP:
 def __init__(self,values):self.values=iter(values);self.calls=[]
 def post(self,url,**kwargs):self.calls.append((url,kwargs));return Response(next(self.values))
def replies(region='eu'):
 return [{'statusCode':100,'body':{'access_token':'fake-session'}},
 {'statusCode':100,'body':{'botRegion':region,'userID':'fake-user'}},
 {'statusCode':100,'body':{'Items':[
  {'device_mac':'AABBCCDDEE01','groupID':'example-group','device_name':'First','device_detail':{'device_type':'W1176000'}},
  {'device_mac':'AABBCCDDEE02','groupID':'example-group','device_name':'Second','device_detail':{'device_type':'W1130000'}},
  {'device_mac':'AABBCCDDEE03','groupID':'example-group','device_detail':{'device_type':'WoPlug'}},
  {'device_mac':'not-an-id','groupID':'example-group','device_detail':{'device_type':'W1130000'}}]}}]
class Tests(unittest.IsolatedAsyncioTestCase):
 async def test_discovery_uses_fresh_identity_and_preserves_password(self):
  http=HTTP(replies());account,frames=await setup.discover_account(http,'Example@invalid.example','  exact password  ')
  self.assertEqual(len(frames),2);self.assertEqual({f['model'] for f in frames},{'frame1','frame2'})
  self.assertEqual(http.calls[0][1]['json']['password'],'  exact password  ')
  self.assertEqual(http.calls[0][1]['json']['username'],'Example@invalid.example')
  self.assertNotEqual(setup.login_template()['request']['deviceInfo']['deviceId'],setup.login_template()['request']['deviceInfo']['deviceId'])
  self.assertEqual(setup.frame_seed(account,frames[0])['device_id'],'AABBCCDDEE01')
 async def test_region_is_not_guessed_or_used_as_arbitrary_host(self):
  http=HTTP(replies('host.invalid'))
  with self.assertRaises(protocol.FrameError):await setup.discover_account(http,'user','password')
  self.assertEqual(len(http.calls),2)
 async def test_us_account_uses_us_host(self):
  http=HTTP(replies('us'));await setup.discover_account(http,'user','password')
  self.assertTrue(http.calls[-1][0].startswith('https://wonderlabs.us.api.switchbot.net/'))
 async def test_bad_login_error_does_not_include_server_body(self):
  http=HTTP([{'statusCode':2020,'message':'secret supplied password'}])
  with self.assertRaises(protocol.FrameError) as error:await setup.discover_account(http,'user','password')
  self.assertNotIn('secret supplied password',str(error.exception))
 def test_runtime_rejects_arbitrary_region_host(self):
  with self.assertRaises(protocol.FrameError):protocol.AppClient(None,{'region':'invalid','session':{'headers':{}},'device_id':'x','group_id':'x'})
if __name__=='__main__':unittest.main()
