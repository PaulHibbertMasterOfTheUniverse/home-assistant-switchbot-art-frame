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
    @staticmethod
    def write_private(path,raw):
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        temporary=path.with_suffix(path.suffix+'.tmp')
        with temporary.open('wb') as file:
            os.chmod(temporary,0o600);file.write(raw);file.flush();os.fsync(file.fileno())
        os.replace(temporary,path)
        descriptor=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)

    def import_transport(self,raw,frame_id,layout,panel_size,metadata,known_layout=False):
        """Keep exact cloud/upload JPEG, plus a reversible gallery presentation.

        Old cloud JPEGs are already prepared transports, NOT camera originals.
        Their historic mounting calibration is unknown; never label inferred
        gallery orientation as historically verified. Exact bytes remain intact.
        """
        digest=hashlib.sha256(raw).hexdigest()
        for existing_id,item in self.read_index().items():
            if digest in (item.get('original_sha256'),item.get('archived_original_sha256')):
                if self.verify_transport(existing_id)==raw:return existing_id
        recipe=json.dumps([frame_id,layout,panel_size],sort_keys=True).encode()
        image_id='transport_'+hashlib.sha256(raw+recipe).hexdigest()[:24]
        with Image.open(io.BytesIO(raw)) as image:
            if image.format!='JPEG' or image.width*image.height>40_000_000:raise ValueError('Invalid transport JPEG')
            image.load();image=image.convert('RGB')
            if layout['orientation']=='portrait':image=image.transpose(Image.Transpose.ROTATE_270)
            if layout['flipped']:image=image.transpose(Image.Transpose.ROTATE_180)
            output=io.BytesIO();image.save(output,'PNG');presentation=output.getvalue()
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        original=self.root/'originals'/(digest+'.jpg')
        if original.exists() and original.read_bytes()!=raw:raise ValueError('Archive collision')
        if not original.exists():self.write_private(original,raw)
        if original.read_bytes()!=raw:raise ValueError('Exact original readback failed')
        self.write_private(self.path(image_id),presentation)
        index=self.read_index();previous=index.get(image_id,{})
        origins=list(previous.get('origins',[]))
        if metadata not in origins:origins.append(metadata)
        index[image_id]={'name':previous.get('name','Imported frame artwork'),
            'saved_at':previous.get('saved_at',datetime.now(timezone.utc).isoformat()),
            'source_kind':'transport_archive','original_sha256':digest,
            'presentation_sha256':hashlib.sha256(presentation).hexdigest(),
            'frame_id':frame_id,'layout_at_archive':dict(layout),'panel_size':panel_size,
            'orientation_provenance':'known_upload_layout' if known_layout else 'historic_layout_unknown_current_layout_used_for_preview',
            'origins':origins}
        self.write_private(self.root/'index.json',json.dumps(index).encode())
        self.verify_transport(image_id)
        return image_id

    def verify_transport(self,image_id):
        item=self.read_index()[image_id]
        digest=item.get('original_sha256',item.get('archived_original_sha256'))
        if not re.fullmatch(r'[a-f0-9]{64}',digest):raise ValueError('Invalid archive digest')
        path=self.root/'originals'/(digest+'.jpg')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Original checksum mismatch')
        if item.get('presentation_sha256') and hashlib.sha256(self.path(image_id).read_bytes()).hexdigest()!=item['presentation_sha256']:
            raise ValueError('Gallery presentation checksum mismatch')
        with Image.open(self.path(image_id)) as image:image.load()
        return raw

    def migration_backup(self, index):
        """No private migration report or artwork is distributed."""
        raise FileNotFoundError('Installation-specific migration backup bridge is not included')

    def list_images(self):
        rows = []
        for image_id, item in self.read_index().items():
            if item.get('trashed_at'):
                continue
            path = self.path(image_id)
            if not path.exists():
                continue
            with Image.open(path) as im:
                im.thumbnail((180, 180))
                buf = io.BytesIO()
                im.convert('RGB').save(buf, 'JPEG', quality=75)
            rows.append({'id': image_id, **item, 'thumbnail': base64.b64encode(buf.getvalue()).decode()})
        return rows
    def download(self, image_id):
        self.path(image_id)
        item = self.read_index()[image_id]
        if item.get('trashed_at'):
            raise KeyError(image_id)
        raw = self.verify_transport(image_id) if item.get('original_sha256') or item.get('archived_original_sha256') else self.path(image_id).read_bytes()
        with Image.open(io.BytesIO(raw)) as image:
            mime = Image.MIME.get(image.format, 'application/octet-stream')
            extension = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}.get(image.format, 'bin')
        name = re.sub('[^a-zA-Z0-9 _-]', '_', item.get('name', 'Artwork')).strip(' _')[:80] or 'Artwork'
        return (raw, mime, name + '.' + extension)

    def trash(self, image_id, restore=False):
        self.path(image_id)
        index = self.read_index()
        item = index[image_id]
        if restore:
            item.pop('trashed_at', None)
        elif not item.get('trashed_at'):
            self.write_private(self.root / 'trash' / (image_id + '.json'), json.dumps(item).encode())
            item['trashed_at'] = datetime.now(timezone.utc).isoformat()
        self.write_private(self.root / 'index.json', json.dumps(index).encode())
        return {'id': image_id, 'trashed': bool(item.get('trashed_at'))}

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
        item=await self.hass.async_add_executor_job(lambda:self.read_index().get(image_id,{}))
        if item.get('trashed_at'):raise ValueError('Artwork is in gallery trash; restore it before sending')
        if item.get('source_kind')=='transport_archive':
            if item['frame_id']!=frame_id or item['panel_size']!=manager.config['panel_size'] or item['layout_at_archive']!=manager.data['layout']:
                raise ValueError('Archived transport belongs to a different frame/layout; review its orientation before conversion')
            raw=await self.hass.async_add_executor_job(self.verify_transport,image_id)
            # Re-upload an already calibrated transport without applying mounting
            # or portrait rotations for a second time.
            return await manager.upload(raw,override_baby=override,expected_layout=dict(item['layout_at_archive']))
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

class ArtworkView(HomeAssistantView):
    url='/api/frame_art_gallery/artwork/{image_id}';name='api:frame_art_gallery:artwork';requires_auth=True
    def __init__(self,gallery):self.gallery=gallery
    async def get(self,request,image_id):
        if not request['hass_user'].is_admin:return self.json({'error':'Administrator access required'},status_code=403)
        try:
            async with self.gallery.lock:
                raw,mime,name=await self.gallery.hass.async_add_executor_job(self.gallery.download,image_id)
            return web.Response(body=raw,content_type=mime,headers={'Content-Disposition':'attachment; filename="'+name+'"','Cache-Control':'no-store'})
        except (ValueError,KeyError,OSError):return self.json({'error':'Artwork not found'},status_code=404)
    async def post(self,request,image_id):
        if not request['hass_user'].is_admin:return self.json({'error':'Administrator access required'},status_code=403)
        body=await request.json()
        if body.get('action') not in ('trash','restore') or body.get('confirm') is not True:
            return self.json({'error':'Explicit trash or restore confirmation required'},status_code=400)
        try:
            async with self.gallery.lock:
                result=await self.gallery.hass.async_add_executor_job(self.gallery.trash,image_id,body['action']=='restore')
            return self.json(result)
        except (ValueError,KeyError,OSError):return self.json({'error':'Artwork not found'},status_code=404)

async def async_setup(hass,config):
    if DOMAIN not in config:return True
    gallery=Gallery(hass,config[DOMAIN]);hass.data[DOMAIN]=gallery
    hass.http.register_view(GalleryView(gallery));hass.http.register_view(ImageView(gallery));hass.http.register_view(ArtworkView(gallery))
    async def send(call):
        try:return await gallery.send(call.data['image_id'],call.data['frame_id'],call.data.get('override_baby',False))
        except Exception as error:
            raise HomeAssistantError('Gallery send failed; check the destination frame status') from None
    hass.services.async_register(DOMAIN,'send_image',send,schema=vol.Schema({
        vol.Required('image_id'):cv.string,vol.Required('frame_id'):cv.slug,
        vol.Optional('override_baby',default=False):cv.boolean}),supports_response=SupportsResponse.OPTIONAL)
    return True
