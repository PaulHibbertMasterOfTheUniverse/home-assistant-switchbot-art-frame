"""Cross-frame routing, isolated persistence and legacy setup regression tests."""
import ast,base64,json,tempfile,types,unittest,sys
from pathlib import Path
from unittest.mock import AsyncMock,Mock
from aiohttp import web
from test_controller import ns,source,Manager,FrameError
from test_fully_local import picture

class View:pass
class ServiceError(Exception):pass
class Vol:
 @staticmethod
 def Optional(v,**kwargs):return v
 @staticmethod
 def Required(v):return v
 @staticmethod
 def In(v):return v
 @staticmethod
 def Coerce(v):return v
 @staticmethod
 def Schema(v):return v
class Store:
 def __init__(self,hass,version,key):self.key=key;self.saved=[]
 async def async_load(self):return None
 async def async_save(self,data):self.saved.append(json.loads(json.dumps(data)))
class States:
 def __init__(self):self.values={};self.published={}
 def is_state(self,entity,state):return self.values.get(entity)==state
 def async_set(self,entity,state,attrs):self.published[entity]=(state,attrs)
class Hass:
 def __init__(self,root):
  self.config=types.SimpleNamespace(path=lambda p:str(Path(root)/p));self.states=States();self.data={}
  self.views=[];self.handlers={};self.listeners=[];self.started=None
  self.http=types.SimpleNamespace(register_view=self.views.append)
  self.services=types.SimpleNamespace(async_register=lambda d,n,f,**k:self.handlers.update({n:f}),async_call=AsyncMock())
  self.bus=types.SimpleNamespace(async_listen_once=lambda event,fn:setattr(self,'started',fn))
 async def async_add_executor_job(self,fn,*args):return fn(*args)
 def async_create_task(self,coro):raise AssertionError('Unexpected task')

def environment():
 env=dict(ns);env.update({'Path':Path,'Store':Store,'web':web,'HomeAssistantView':View,'HomeAssistantError':ServiceError,
   'vol':Vol,'cv':types.SimpleNamespace(slug=str,boolean=bool),'binascii':__import__('binascii'),'EVENT_HOMEASSISTANT_STARTED':'started',
   'AppClient':lambda http,seed:types.SimpleNamespace(device=seed['device_id']),
   'async_track_state_change_event':lambda h,e,fn:h.listeners.append((e,fn)), '__package__':'frame_test'})
 tree=ast.parse(source.read_text());names={'frame_configs','FrameRegistry','FramesView','PrepareView','ArchiveView','UploadView','load_manager','async_setup','Manager'}
 nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name in names]
 exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),env)
 return env
class Request(dict):
 content_length=100
 def __init__(self,payload,admin=True):super().__init__(hass_user=types.SimpleNamespace(is_admin=admin));self.payload=payload
 async def json(self):return self.payload
class Tests(unittest.IsolatedAsyncioTestCase):
 async def test_two_frames_have_separate_stores_keys_states_locks_and_switch_callbacks(self):
  env=environment()
  with tempfile.TemporaryDirectory() as root:
   h=Hass(root);settings={'frames':[],'default_frame':'main_frame'}
   for fid,mac in [('main_frame','AABBCCDDEE01'),('studio','AABBCCDDEE02')]:
    Path(root,fid+'.json').write_text(json.dumps({'device_id':mac,'communication_key':{'key':fid}}))
    settings['frames'].append({'id':fid,'device_id':mac,'local_key_file':fid+'.json','waterfall_entity':'switch.'+fid})
   fake=types.ModuleType('frame_test.generation');fake.GenerateView=lambda registry:object()
   old=sys.modules.get('frame_test.generation');sys.modules['frame_test.generation']=fake
   try:await env['async_setup'](h,{'switchbot_frame_control':settings})
   finally:
    if old is None:sys.modules.pop('frame_test.generation',None)
    else:sys.modules['frame_test.generation']=old
   registry=h.data['switchbot_frame_control'];a=registry.select('main_frame');b=registry.select('studio')
   self.assertNotEqual(a.store.key,b.store.key);self.assertIsNot(a.lock,b.lock);self.assertIsNot(a.data,b.data)
   self.assertNotEqual(a.local_key,b.local_key);self.assertEqual(set(h.states.published),{'sensor.main_frame_frame_control','sensor.studio_frame_control'})
   a.schedule=Mock();b.schedule=Mock()
   h.states.values['switch.studio']='on';h.listeners[1][1](types.SimpleNamespace(data={'old_state':None,'new_state':types.SimpleNamespace(state='on')}))
   b.schedule.assert_called_once();a.schedule.assert_not_called();self.assertTrue(b.desired());self.assertFalse(a.desired())
   a.reconcile=AsyncMock();b.reconcile=AsyncMock()
   await h.handlers['show_baby'](types.SimpleNamespace(data={'frame_id':'studio'}))
   self.assertTrue(b.data['manual_baby']);self.assertFalse(a.data['manual_baby']);b.reconcile.assert_awaited_once();a.reconcile.assert_not_awaited()
   self.assertIs(registry.select(),a)
 async def test_missing_and_unknown_targets_cannot_upload_to_either_frame(self):
  env=environment();a=types.SimpleNamespace(upload=AsyncMock());b=types.SimpleNamespace(upload=AsyncMock())
  registry=env['FrameRegistry'](None,{'one':a,'two':b});view=env['UploadView'](registry)
  for payload in ({'image':'eA=='},{'frame_id':'missing','image':'eA=='}):
   response=await view.post(Request(payload));self.assertEqual(response.status,400)
  a.upload.assert_not_awaited();b.upload.assert_not_awaited()
 async def test_http_upload_routes_only_selected_frame(self):
  env=environment();a=types.SimpleNamespace(upload=AsyncMock(return_value={'sent':True}));b=types.SimpleNamespace(upload=AsyncMock(return_value={'sent':True}))
  view=env['UploadView'](env['FrameRegistry'](None,{'one':a,'two':b}))
  r=await view.post(Request({'frame_id':'two','image':base64.b64encode(picture()).decode(),'override_baby':True}))
  self.assertEqual(r.status,200);a.upload.assert_not_awaited();b.upload.assert_awaited_once_with(picture(),override_baby=True,replace_index=None)
 async def test_admin_required_and_list_contains_no_private_keys(self):
  env=environment();m=types.SimpleNamespace(frame_id='one',name='One',entity_id='sensor.one',config={},local_key={'secret':'not public'})
  view=env['FramesView'](env['FrameRegistry'](None,{'one':m}))
  self.assertEqual((await view.get(Request({},False))).status,403)
  r=await view.get(Request({}));self.assertNotIn('secret',r.text);self.assertEqual(json.loads(r.text)['frames'][0]['id'],'one')
 async def test_configuration_rejects_duplicate_devices_keys_entities_ids(self):
  env=environment();base={'id':'one','device_id':'AA','local_key_file':'a.json'}
  for other in ({'id':'one','device_id':'BB','local_key_file':'b.json'},{'id':'two','device_id':'AA','local_key_file':'b.json'},{'id':'two','device_id':'BB','local_key_file':'a.json'},{'id':'two','device_id':'BB','local_key_file':'b.json','status_entity':'sensor.one_frame_control'}):
   with self.assertRaises(FrameError):env['frame_configs']({'frames':[base,other]})
 async def test_legacy_entity_and_single_frame_service_default_preserved(self):
  env=environment();cfg=env['frame_configs']({'device_id':'legacy-cloud-id','credentials_file':'private.json'})[0]
  self.assertEqual(cfg['id'],'main_frame');self.assertEqual(cfg['status_entity'],'sensor.main_frame_frame_control');self.assertTrue(cfg['_legacy'])
  m=object();self.assertIs(env['FrameRegistry'](None,{'main_frame':m}).select(),m)

 async def test_artwork_only_frame_restores_without_provisioning_baby(self):
  from test_fully_local import setup
  m,f=setup(False,indices=(7,8),mode='0101001e')
  m.config.pop('waterfall_entity');m.read_local_baby=AsyncMock(side_effect=AssertionError('No baby provisioning'))
  await m.reconcile();f.normal.assert_awaited_once_with([7,8]);f.show.assert_not_awaited();m.read_local_baby.assert_not_awaited()
  self.assertEqual(m.status,'normal')
