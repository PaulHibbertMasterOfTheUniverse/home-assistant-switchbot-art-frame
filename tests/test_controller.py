import ast,asyncio,base64,io,json,sys,types,unittest
from pathlib import Path
from unittest.mock import AsyncMock
from PIL import Image,ImageOps,UnidentifiedImageError
ROOT=Path(__file__).parent.parent
source=ROOT/'custom_components/switchbot_frame_control/__init__.py'
protocol={};exec((source.parent/'protocol.py').read_text(),protocol)
FrameError=protocol['FrameError'];AppClient=protocol['AppClient']
class Store:
    def __init__(self,*args):self.saved=[]
    async def async_save(self,data):self.saved.append(json.loads(json.dumps(data)))
class States:
    def __init__(self,on=False):self.on=on;self.published=[]
    def is_state(self,entity,state):return self.on==(state=='on')
    def async_set(self,*args):self.published.append(args)
class Hass:
    def __init__(self,on=False):self.states=States(on);self.services=types.SimpleNamespace(async_call=AsyncMock())
    async def async_add_executor_job(self,func,*args):return func(*args)
ns={'AsyncExitStack':__import__('contextlib').AsyncExitStack,'asyncio':asyncio,'base64':base64,'io':io,'json':json,'time':__import__('time'),'hashlib':__import__('hashlib'),
    'Image':Image,'ImageOps':ImageOps,'UnidentifiedImageError':UnidentifiedImageError,
    'FrameError':FrameError,'AppClient':lambda *args:None,'Store':Store,'callback':lambda f:f,
    'async_get_clientsession':lambda hass:None,'MAX_SOURCE_FILE':64*1024*1024,'MAX_FILE':8*1024*1024,'DOMAIN':'switchbot_frame_control'}
tree=ast.parse(source.read_text());nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in ('prepare_source','jpeg_bytes','image_signature','signatures_match','Manager')]
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),ns)
Manager=ns['Manager']
native={};exec((source.parent/'native_image.py').read_text(),native)
ns['panel_bytes']=native['panel_bytes']
def manager(on=False):
    h=Hass(on);m=Manager(h,{'credentials_file':'private.json','waterfall_entity':'input_boolean.baby_waterfall_sounds','baby_image_url':'https://example.invalid/baby.jpg'}, {'device_id':'FRAME'})
    m.client=types.SimpleNamespace(catalogue=AsyncMock(return_value=[{'imageIndex':7},{'imageIndex':8}]),normal=AsyncMock(),remove=AsyncMock(),show=AsyncMock())
    m.wait_native_idle=AsyncMock()
    return m
class Tests(unittest.IsolatedAsyncioTestCase):
    async def test_image_download_collects_all_network_chunks(self):
        out=io.BytesIO();Image.new('RGB',(90,60),'red').save(out,'JPEG');raw=out.getvalue()
        class Response:
            status=200
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            @property
            def content(self):return self
            async def iter_chunked(self,n):
                for offset in range(0,len(raw),17):yield raw[offset:offset+17]
        old=ns['async_get_clientsession']
        ns['async_get_clientsession']=lambda hass:types.SimpleNamespace(get=lambda *a,**k:Response())
        try:
            result=await manager().read_image('https://example.invalid/image')
            with Image.open(io.BytesIO(result)) as image:self.assertEqual(image.size,(90,60))
        finally:ns['async_get_clientsession']=old
    async def test_protocol_delete_is_targeted_and_verified(self):
        c=AppClient(None,{'session':{'headers':{}},'device_id':'D','group_id':'G'});c.invoke=AsyncMock();c.post=AsyncMock();c.catalogue=AsyncMock(return_value=[{'imageIndex':7}])
        await c.remove([8]);c.invoke.assert_awaited_once_with(9625,{'0':1,'1':[8]})
        for call in c.post.call_args_list:self.assertIs(call.args[1]['deleteAll'],False)
    async def test_still_present_delete_raises(self):
        c=AppClient(None,{'session':{'headers':{}},'device_id':'D','group_id':'G'});c.invoke=AsyncMock();c.post=AsyncMock();c.catalogue=AsyncMock(return_value=[{'imageIndex':8}])
        with self.assertRaises(FrameError):await c.remove([8])
    async def test_normal_playlist_has_expected_indices(self):
        c=AppClient(None,{'session':{'headers':{}},'device_id':'D','group_id':'G'});c.invoke=AsyncMock()
        await c.normal([7,9]);self.assertEqual(c.invoke.call_args.args,(9627,{'0':30,'1':0,'2':1440,'3':127,'4':[7,9]}))
    async def test_signature_rejects_different_image(self):
        def image(color):
            out=io.BytesIO();Image.new('RGB',(400,300),color).save(out,'PNG');return out.getvalue()
        a=ns['image_signature'](image('red'));b=ns['image_signature'](image('blue'))
        self.assertFalse(ns['signatures_match'](a,b));self.assertTrue(ns['signatures_match'](a,a))
    async def test_switchbot_crop_and_rotation_recognised(self):
        image=Image.new('RGB',(640,360));image.putdata([(x*255//640,y*255//360,(x+y)*255//1000) for y in range(360) for x in range(640)])
        before=io.BytesIO();image.save(before,'JPEG',quality=95);original=before.getvalue()
        after=io.BytesIO();ImageOps.fit(image,(480,360)).rotate(90,expand=True).save(after,'JPEG',quality=95);stored=after.getvalue()
        self.assertTrue(ns['signatures_match'](ns['image_signature'](original),ns['image_signature'](stored)))
    async def test_png_converts_to_jpeg(self):
        out=io.BytesIO();Image.new('RGBA',(30,20),(0,255,0,128)).save(out,'PNG')
        converted=ns['jpeg_bytes'](out.getvalue());self.assertTrue(converted.startswith(b'\xff\xd8'))
if __name__=='__main__':unittest.main()
