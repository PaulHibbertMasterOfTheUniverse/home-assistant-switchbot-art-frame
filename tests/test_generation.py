import ast,asyncio,base64,binascii,json,re,unittest
from pathlib import Path
from types import SimpleNamespace
source=Path(__file__).parent.parent/'custom_components/switchbot_frame_control/generation.py'
class FrameError(Exception):pass
ns=dict(asyncio=asyncio,base64=base64,binascii=binascii,json=json,re=re,FrameError=FrameError,MODEL='@cf/black-forest-labs/flux-1-schnell',MAX_RESPONSE=16*1024*1024)
tree=ast.parse(source.read_text());node=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='generate_image')
exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),ns)
class Response:
    def __init__(self,status=200,body=None):self.status=status;self.body=body
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    @property
    def content(self):return self
    async def iter_chunked(self,n):
        data=json.dumps(self.body).encode()
        for i in range(0,len(data),5):yield data[i:i+5]
class Tests(unittest.IsolatedAsyncioTestCase):
    async def test_success_and_scoped_endpoint(self):
        calls=[]
        def post(url,**kwargs):
            calls.append((url,kwargs));return Response(body={'success':True,'result':{'image':base64.b64encode(b'image').decode()}})
        result=await ns['generate_image'](SimpleNamespace(post=post),{'account_id':'a'*32,'api_token':'private'},'woodland')
        self.assertEqual(result,b'image');self.assertIn('/accounts/'+'a'*32+'/ai/run/',calls[0][0]);self.assertEqual(calls[0][1]['json'],{'prompt':'woodland','steps':4})
    async def test_quota_failure_is_not_retried(self):
        calls=[]
        def post(*a,**k):calls.append(1);return Response(429)
        with self.assertRaisesRegex(FrameError,'allowance'):await ns['generate_image'](SimpleNamespace(post=post),{'account_id':'a'*32,'api_token':'private'},'test')
        self.assertEqual(len(calls),1)
    async def test_bad_account_rejected_before_network(self):
        with self.assertRaisesRegex(FrameError,'configured'):await ns['generate_image'](None,{'account_id':'../escape','api_token':'private'},'test')
    async def test_invalid_image_rejected(self):
        http=SimpleNamespace(post=lambda *a,**k:Response(body={'success':True,'result':{'image':'invalid!'}}))
        with self.assertRaises(FrameError):await ns['generate_image'](http,{'account_id':'a'*32,'api_token':'private'},'test')
if __name__=='__main__':unittest.main()

class ViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_allowed_while_baby_is_active(self):
        import tempfile
        from unittest.mock import AsyncMock,Mock
        from aiohttp import web
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'cloudflare_frame_private.json').write_text('{}')
            fake_hass=SimpleNamespace(config=SimpleNamespace(path=lambda name:str(Path(folder,name))),async_add_executor_job=AsyncMock(side_effect=lambda fn,*args:fn(*args)))
            manager=SimpleNamespace(hass=fake_hass,desired=Mock(side_effect=AssertionError('Preview must not depend on display state')))
            node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='GenerateView')
            class RemoveRelativeImport(ast.NodeTransformer):
                def visit_ImportFrom(self,node):return None if node.level else node
            node=RemoveRelativeImport().visit(ast.parse(ast.unparse(node)).body[0]);ast.fix_missing_locations(node)
            scope={**ns,'HomeAssistantView':object,'web':web,'Path':Path,'async_get_clientsession':lambda hass:None,'generate_image':AsyncMock(return_value=b'jpeg'),'jpeg_bytes':lambda raw:raw}
            exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),scope)
            class Request(dict):
                content_length=20
                async def json(self):return {'prompt':'A blue truck'}
            response=await scope['GenerateView'](manager).post(Request(hass_user=SimpleNamespace(is_admin=True)))
            self.assertEqual(response.status,200);manager.desired.assert_not_called()
