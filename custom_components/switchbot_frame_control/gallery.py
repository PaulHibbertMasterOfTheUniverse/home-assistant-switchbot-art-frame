"""Private, authenticated Home Assistant artwork library and automation service."""
import asyncio
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import os
from datetime import datetime, timezone

from aiohttp import web
from PIL import Image, ImageOps
import voluptuous as vol
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

DOMAIN='frame_art_gallery'
CONFIG_SCHEMA=vol.Schema({DOMAIN:vol.Schema({vol.Optional('directory',default='frame_art_gallery'):cv.string})},extra=vol.ALLOW_EXTRA)

def normalise(raw):
    from . import prepare_source
    return prepare_source(raw,2560)

def prepare_transport(raw,layout,size):
    dimensions={'7.3':(800,480),'13.3':(1600,1200),'31.5':(2560,1440)}
    wide,tall=dimensions[size]
    with Image.open(io.BytesIO(raw)) as source:
        source=ImageOps.exif_transpose(source).convert('RGB')
        portrait=layout.get('orientation')=='portrait'
        image=ImageOps.fit(source,(tall,wide) if portrait else (wide,tall),method=Image.Resampling.LANCZOS)
        if layout.get('flipped'):image=image.transpose(Image.Transpose.ROTATE_180)
        if portrait:image=image.transpose(Image.Transpose.ROTATE_90)
        output=io.BytesIO();image.save(output,'JPEG',quality=92);return output.getvalue()

class Gallery:
    def __init__(self,hass,config):
        self.hass=hass;self.root=Path(hass.config.path(config['directory'])).resolve();self.lock=asyncio.Lock()
        if not self.root.is_relative_to(Path(hass.config.config_dir).resolve()):raise ValueError('Gallery directory must be inside Home Assistant configuration')
    def path(self,image_id):
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}',image_id):raise ValueError('Invalid artwork ID')
        return self.root/(image_id+'.jpg')
    def read_index(self):
        p=self.root/'index.json'
        return json.loads(p.read_text()) if p.exists() else {}
    def list_images(self):
        rows=[]
        for image_id,item in self.read_index().items():
            path=self.path(image_id)
            if not path.exists():continue
            with Image.open(path) as im:
                im.thumbnail((180,180));buf=io.BytesIO();im.convert('RGB').save(buf,'JPEG',quality=75)
            rows.append({'id':image_id,**item,'thumbnail':base64.b64encode(buf.getvalue()).decode()})
        return rows
    def save_image(self,raw,name):
        raw=normalise(raw);image_id='art_'+hashlib.sha256(raw).hexdigest()[:24]
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        path=self.path(image_id);tmp=path.with_suffix('.tmp');tmp.write_bytes(raw);os.replace(tmp,path)
        index=self.read_index();index[image_id]={'name':name[:100],'saved_at':datetime.now(timezone.utc).isoformat()}
        dest=self.root/'index.json';temp=dest.with_suffix('.tmp');temp.write_text(json.dumps(index));os.replace(temp,dest)
        return image_id
    def import_bin_artwork(self):
        return {kind:self.save_image((Path(__file__).parent/'examples'/(kind+'-bin.jpg')).read_bytes(),label)
                for kind,label in [('blue','Blue bin'),('black','Black bin'),('none','No bin collection today')]}

    async def send(self,image_id,frame_id,override=False):
        manager=self.hass.data['switchbot_frame_control'].select(frame_id)
        raw=await self.hass.async_add_executor_job(self.path(image_id).read_bytes)
        layout=dict(manager.data.get('layout',{'orientation':'landscape','flipped':False}))
        transport=await self.hass.async_add_executor_job(prepare_transport,raw,layout,manager.config['panel_size'])
        return await manager.upload(transport,override_baby=override,expected_layout=layout)

class GalleryView(HomeAssistantView):
    url='/api/frame_art_gallery';name='api:frame_art_gallery';requires_auth=True
    def __init__(self,gallery):self.gallery=gallery
    async def get(self,request):
        if not request['hass_user'].is_admin:return self.json({'error':'Administrator access required'},status_code=403)
        rows=await self.gallery.hass.async_add_executor_job(self.gallery.list_images)
        return self.json({'images':rows,'service':'frame_art_gallery.send_image'})
    async def post(self,request):
        if not request['hass_user'].is_admin:return self.json({'error':'Administrator access required'},status_code=403)
        try:
            data=await request.json()
            if data.get('action')=='import_bin_artwork':
                async with self.gallery.lock:
                    ids=await self.gallery.hass.async_add_executor_job(self.gallery.import_bin_artwork)
                return self.json({'images':ids})
            raw=base64.b64decode(data['image'],validate=True)
            if len(raw)>8*1024*1024:raise ValueError('Prepared picture exceeds 8 MB; prepare the source first')
            name=str(data.get('name','Artwork')).strip() or 'Artwork'
            async with self.gallery.lock:
                image_id=await self.gallery.hass.async_add_executor_job(self.gallery.save_image,raw,name)
            return self.json({'id':image_id})
        except (ValueError,KeyError,OSError):return self.json({'error':'Could not save this image to the gallery'},status_code=400)

class ImageView(HomeAssistantView):
    url='/api/frame_art_gallery/image/{image_id}';name='api:frame_art_gallery:image';requires_auth=True
    def __init__(self,gallery):self.gallery=gallery
    async def get(self,request,image_id):
        if not request['hass_user'].is_admin:return self.json({'error':'Administrator access required'},status_code=403)
        try:raw=await self.gallery.hass.async_add_executor_job(self.gallery.path(image_id).read_bytes)
        except (ValueError,OSError):return self.json({'error':'Artwork not found'},status_code=404)
        return self.json({'image':base64.b64encode(raw).decode(),'id':image_id})

async def async_setup(hass,config):
    if DOMAIN not in config:return True
    gallery=Gallery(hass,config[DOMAIN]);hass.data[DOMAIN]=gallery
    hass.http.register_view(GalleryView(gallery));hass.http.register_view(ImageView(gallery))
    async def send(call):
        try:return await gallery.send(call.data['image_id'],call.data['frame_id'],call.data.get('override_baby',False))
        except Exception as error:
            raise HomeAssistantError('Gallery send failed; check the destination frame status') from None
    hass.services.async_register(DOMAIN,'send_image',send,schema=vol.Schema({
        vol.Required('image_id'):cv.string,vol.Required('frame_id'):cv.slug,
        vol.Optional('override_baby',default=False):cv.boolean}),supports_response=SupportsResponse.OPTIONAL)
    return True
