"""Cloudflare image generation; credentials stay on the Home Assistant server."""
import asyncio
import base64
import binascii
import json
import re
from pathlib import Path
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .protocol import FrameError

MODEL='@cf/black-forest-labs/flux-1-schnell'
MAX_RESPONSE=16*1024*1024

async def generate_image(http,credentials,prompt):
    account=credentials.get('account_id','')
    token=credentials.get('api_token','')
    if not re.fullmatch(r'[a-fA-F0-9]{32}',account) or not token:
        raise FrameError('Cloudflare image generation is not configured')
    url=f'https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{MODEL}'
    try:
        async with http.post(url,headers={'Authorization':'Bearer '+token},
                json={'prompt':prompt,'steps':4},timeout=120) as response:
            if response.status==429:raise FrameError('Cloudflare allowance or rate limit reached. Try later; no automatic retry was made')
            if response.status in (401,403):raise FrameError('Cloudflare rejected the image-generation credentials or permissions')
            if response.status!=200:raise FrameError('Cloudflare could not generate this image. Try again later')
            chunks=[];size=0
            async for chunk in response.content.iter_chunked(65536):
                size+=len(chunk)
                if size>MAX_RESPONSE:raise FrameError('Generated image response was too large')
                chunks.append(chunk)
        result=json.loads(b''.join(chunks))
        if result.get('success') is not True:raise FrameError('Cloudflare did not complete image generation')
        encoded=result.get('result',{}).get('image','')
        raw=base64.b64decode(encoded,validate=True)
        if not raw or len(raw)>8*1024*1024:raise FrameError('Cloudflare returned an invalid or oversized image')
        return raw
    except (asyncio.TimeoutError,OSError) as error:
        raise FrameError('Image generation timed out. No automatic retry was made') from error
    except (ValueError,binascii.Error,TypeError,AttributeError) as error:
        raise FrameError('Cloudflare returned an unreadable image response') from error

class GenerateView(HomeAssistantView):
    url='/api/switchbot_frame_control/generate'
    name='api:switchbot_frame_control:generate'
    requires_auth=True
    def __init__(self,manager):self.manager=manager;self.busy=False
    async def post(self,request):
        user=request.get('hass_user')
        if not user or not user.is_admin:return web.json_response({'error':'Administrator access required'},status=403)
        if self.busy:return web.json_response({'error':'An image is already being generated'},status=429)
        if request.content_length and request.content_length>10000:return web.json_response({'error':'Description is too long'},status=413)
        self.busy=True
        try:
            payload=await request.json();prompt=payload.get('prompt','')
            if not isinstance(prompt,str) or not 1<=len(prompt.strip())<=2048:
                raise FrameError('Enter a picture description between 1 and 2048 characters')
            selected=self.manager.select(payload.get('frame_id')) if hasattr(self.manager,'select') else None
            if selected and selected.config.get('_entry_id'):
                saved=selected.config.get('_generation',{})
                credentials={'account_id':saved.get('cloudflare_account_id',''),'api_token':saved.get('cloudflare_api_token','')}
            else:
                path=Path(self.manager.hass.config.path('cloudflare_frame_private.json'))
                try:
                    credentials=json.loads(await self.manager.hass.async_add_executor_job(path.read_text))
                except (OSError,ValueError):raise FrameError('Cloudflare image generation is not configured') from None
            raw=await generate_image(async_get_clientsession(self.manager.hass),credentials,prompt.strip())
            from . import jpeg_bytes
            raw=await self.manager.hass.async_add_executor_job(jpeg_bytes,raw)
            return web.json_response({'image':base64.b64encode(raw).decode(),'mime_type':'image/jpeg'})
        except FrameError as error:return web.json_response({'error':str(error)},status=400)
        except Exception:return web.json_response({'error':'Image generation failed'},status=502)
        finally:self.busy=False
