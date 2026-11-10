"""Authenticated dashboard uploads and a tracked, removable baby notification."""
import asyncio
import base64
import binascii
import hashlib
from datetime import timedelta
import io
import os
from contextlib import asynccontextmanager, AsyncExitStack
import json
from pathlib import Path
import time

from aiohttp import web
from PIL import Image, ImageOps, UnidentifiedImageError
import voluptuous as vol
from homeassistant.components.http import HomeAssistantView
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from .protocol import AppClient, FrameError
from .native_image import panel_bytes
from .replacement import Replacement

DOMAIN='switchbot_frame_control'
FRAME_SCHEMA=vol.Schema({
    vol.Optional('id'):cv.slug,vol.Optional('name'):cv.string,
    vol.Optional('model',default='frame2'):vol.In(['frame1','frame2']),
    vol.Optional('connection_mode'):vol.In(['local','hybrid','wifi']),
    vol.Optional('panel_size'):vol.In(['7.3','13.3','31.5']),
    vol.Optional('credentials_file'):cv.string,vol.Required('device_id'):cv.string,
    vol.Optional('local_key_file',default='frame_local_private.json'):cv.string,
    vol.Optional('baby_image_file',default='frame_baby_asleep.jpg'):cv.string,
    vol.Optional('baby_image_url'):cv.url,vol.Optional('waterfall_entity'):cv.entity_id,
    vol.Optional('status_entity'):cv.entity_id})
CONFIG_SCHEMA=vol.Schema({DOMAIN:vol.Any(FRAME_SCHEMA,vol.Schema({
    vol.Required('frames'):vol.All(cv.ensure_list,[FRAME_SCHEMA]),vol.Optional('default_frame'):cv.slug}))},extra=vol.ALLOW_EXTRA)

def frame_configs(settings):
    """Normalize legacy configuration without changing its entity or store."""
    frames=settings.get('frames') if 'frames' in settings else [settings]
    if not frames:raise FrameError('Configure at least one frame')
    result=[];ids=set();devices=set();entities=set();key_files=set()
    for number,source in enumerate(frames):
        item=dict(source);legacy='frames' not in settings;item['_legacy']=legacy
        item.setdefault('id','main_frame' if legacy else '')
        if not isinstance(item['id'],str) or not item['id'] or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_' for c in item['id']):raise FrameError('Each frame needs a unique id')
        item.setdefault('name','Main art frame' if legacy else item['id'].replace('_',' ').title())
        item.setdefault('status_entity','sensor.main_frame_frame_control' if legacy else 'sensor.'+item['id']+'_frame_control')
        item.setdefault('local_key_file','frame_local_private.json')
        item.setdefault('baby_image_file','frame_baby_asleep.jpg')
        size=item.get('panel_size','7.3' if item.get('model')=='frame1' else '13.3')
        if item.get('model','frame2')=='frame2' and size!='13.3':raise FrameError('Only the 13.3-inch Frame 2 profile is validated')
        item['panel_size']=size
        device=item['device_id'].replace(':','').upper()
        if item['id'] in ids or device in devices or item['status_entity'] in entities or item['local_key_file'] in key_files:
            raise FrameError('Frame ids, devices, status entities and local key files must be unique')
        if not item['status_entity'].startswith('sensor.'):raise FrameError('Frame status entity must be a sensor')
        ids.add(item['id']);devices.add(device);entities.add(item['status_entity']);key_files.add(item['local_key_file']);result.append(item)
    return result

class FrameRegistry:
    """Explicit routing: multiple frames never silently use the first device."""
    def __init__(self,hass,managers,default_frame=None):
        self.hass=hass;self.managers=managers;self.default_frame=default_frame
        if default_frame is not None and default_frame not in managers:raise FrameError('default_frame must name a configured frame')
    def select(self,frame_id=None):
        if frame_id is None:
            if self.default_frame is not None:return self.managers[self.default_frame]
            if len(self.managers)==1:return next(iter(self.managers.values()))
            raise FrameError('Choose a frame using frame_id')
        if not isinstance(frame_id,str) or frame_id not in self.managers:raise FrameError('Unknown frame_id')
        return self.managers[frame_id]
    def descriptions(self):
        return [{'id':m.frame_id,'name':m.name,'status_entity':m.entity_id,
                 'notification_configured':bool(m.config.get('waterfall_entity')),'waterfall_entity':m.config.get('waterfall_entity'),
                 'local_ready':bool(m.local_key),'model':m.config.get('model','frame2'),
                 'panel_size':m.config.get('panel_size','7.3' if m.config.get('model')=='frame1' else '13.3'),
                 'width':{'7.3':800,'13.3':1600,'31.5':2560}[m.config.get('panel_size','7.3' if m.config.get('model')=='frame1' else '13.3')],
                 'height':{'7.3':480,'13.3':1200,'31.5':1440}[m.config.get('panel_size','7.3' if m.config.get('model')=='frame1' else '13.3')],
                 'layout':getattr(m,'data',{}).get('layout',{'orientation':'landscape','flipped':False}),
                 'layout_revision':getattr(m,'data',{}).get('layout_revision',0),
                 'wifi_available':bool(m.config.get('credentials_file'))} for m in self.managers.values()]

MAX_FILE=8*1024*1024
MAX_SOURCE_FILE=64*1024*1024

def prepare_source(raw,bound):
    if len(raw)>MAX_SOURCE_FILE:raise FrameError('Choose an original picture smaller than 64 MB')
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.width*source.height>80_000_000:raise FrameError('Choose a picture with no more than 80 megapixels')
            if source.format=='JPEG':source.draft('RGB',(bound,bound))
            image=ImageOps.exif_transpose(source)
            image.thumbnail((bound,bound),Image.Resampling.LANCZOS)
            image=image.convert('RGB')
            output=io.BytesIO();image.save(output,'JPEG',quality=94)
            return output.getvalue()
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError) as error:
        raise FrameError('This file could not be read as an image') from error

def jpeg_bytes(raw):
    if len(raw)>MAX_FILE: raise FrameError('Please choose an image smaller than 8 MB')
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.width*source.height>40_000_000: raise FrameError('Image dimensions are too large')
            source=ImageOps.exif_transpose(source).convert('RGB')
            source.thumbnail((2400,2400))
            output=io.BytesIO();source.save(output,'JPEG',quality=92)
            return output.getvalue()
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError) as error:
        raise FrameError('This file could not be read as an image') from error

def image_signature(raw):
    with Image.open(io.BytesIO(raw)) as image:
        image=ImageOps.exif_transpose(image).convert('RGB')
        aspect=image.width/image.height
        image=image.resize((24,24))
        return {'aspect':aspect,'pixels':list(image.tobytes())}

def signatures_match(a,b):
    # SwitchBot centre-crops to its panel aspect and may rotate the stored copy.
    left=Image.frombytes('RGB',(24,24),bytes(a['pixels']))
    right=Image.frombytes('RGB',(24,24),bytes(b['pixels']))
    for angle in (0,90,180,270):
        candidate=right.rotate(angle)
        aspect=b['aspect'] if angle in (0,180) else 1/b['aspect']
        expected=left
        if abs(a['aspect']-aspect)>0.03:
            if a['aspect']>aspect:
                width=24*aspect/a['aspect']
                expected=left.crop(((24-width)/2,0,(24+width)/2,24))
            else:
                height=24*a['aspect']/aspect
                expected=left.crop((0,(24-height)/2,24,(24+height)/2))
            expected=expected.resize((24,24))
        if sum(abs(x-y) for x,y in zip(expected.tobytes(),candidate.tobytes()))/1728 < 5:
            return True
    return False

class Manager:
    def __init__(self,hass,config,seed):
        self.hass=hass;self.config=config
        self.frame_id=config.get('id','main_frame');self.name=config.get('name','Main art frame')
        self.entity_id=config.get('status_entity','sensor.main_frame_frame_control')
        self.client=AppClient(async_get_clientsession(hass),seed)
        self.lock=asyncio.Lock();self.tasks=set()
        self.store=Store(hass,1,DOMAIN+'.'+seed['device_id'],atomic_writes=True)
        self.data={'baby_indices':[],'normal_indices':[],'pending':None,'manual_baby':False}
        self.error=None;self.status='ready';self.last_action='';self.source=''
        self.local_key=None
        self.last_transport='';self.last_storage_verified=False

    @callback
    def publish(self,status=None,error=None):
        if status:self.status=status
        self.error=error
        self.hass.states.async_set(self.entity_id,self.status,
            {'friendly_name':self.name,'frame_id':self.frame_id,'icon':'mdi:image-frame',
             'last_action':self.last_action,'error':self.error,
             'baby_picture_stored':bool(self.data['baby_indices']),
             'baby_notification_active':self.desired(),
             'manual_baby_active':bool(self.data.get('manual_baby')),
             'waterfall_on':self.waterfall_on(),
             'connection_mode':self.connection_mode(),'frame_model':self.config.get('model','frame2'),
             'cloud_connection':self.connection_mode()!='local','control_transport':self.last_transport or self.connection_mode(),
             'baby_retained_for_local_control':bool(self.local_key),
             'download_wait':self.data.get('last_download_wait',[]),
             'last_transfer':self.data.get('last_transfer',{}),
             'archive_available':bool(self.data.get('last_archived_art')),
             'layout':dict(self.data.get('layout',{'orientation':'landscape','flipped':False})),
             'layout_revision':self.data.get('layout_revision',0),
             'replacement':{key:self.data.get('pending_replacement',self.data.get('last_replacement',{})).get(key)
                            for key in ('index','stage','started_at','updated_at','release_requests','cloud_delete_requests','cloud_sync_requests','events')},
             'display_confirmation':'Frame-reported mode' if self.last_storage_verified else 'Not physically verified'})

    def connection_mode(self):
        return self.data.get('connection_mode',self.config.get('connection_mode','hybrid' if self.config.get('model')=='frame1' else 'local'))

    async def set_connection_mode(self,mode):
        if mode not in ('local','hybrid','wifi'):raise FrameError('Choose local, hybrid or wifi mode')
        async with self.lock:
            if mode!='local' and not self.config.get('credentials_file'):
                raise FrameError('Wi-Fi/cloud access has not been configured for this frame')
            if mode=='local' and not self.local_key:raise FrameError('This frame has no Bluetooth key configured')
            self.data['connection_mode']=mode;await self.save()
            self.last_action={'local':'Bluetooth only. No automatic cloud fallback.',
                'hybrid':'Bluetooth where available; SwitchBot cloud over Wi-Fi when needed.',
                'wifi':'Wi-Fi/cloud only. Bluetooth will not be used.'}[mode]
            self.publish('ready')

    def check_index(self,index):
        limit=255 if self.config.get('model')=='frame1' else 20480
        if isinstance(index,bool) or not isinstance(index,int) or not 1<=index<=limit:
            raise FrameError('Invalid image index for this frame generation')
        return index

    def mode_matches(self,mode,index):
        value=bytes.fromhex(mode)
        width=1 if self.config.get('model')=='frame1' else 2
        return len(value)>=2+width and value[0]==1 and value[1]==0 and int.from_bytes(value[2:2+width],'little')==index

    async def set_layout(self,layout,expected_revision=None):
        if not isinstance(layout,dict) or set(layout)!={'orientation','flipped'} or layout.get('orientation') not in ('landscape','portrait') or type(layout.get('flipped')) is not bool:
            raise FrameError('Choose landscape or portrait and a valid 180-degree setting')
        async with self.lock:
            if expected_revision is not None and expected_revision!=self.data.get('layout_revision',0):
                raise FrameError('Saved layout changed in another session. Reload this dashboard before saving orientation')
            if self.data.get('layout')!=layout:
                previous=self.data.get('layout');revision=self.data.get('layout_revision',0)
                self.data['layout']=dict(layout)
                self.data['layout_revision']=revision+1
                try:await self.save_verified()
                except Exception:
                    if previous is None:self.data.pop('layout',None)
                    else:self.data['layout']=previous
                    self.data['layout_revision']=revision
                    raise
            self.publish(error=self.error)
        return self.data['layout']

    def protected_indices(self):
        indices=set(self.data['baby_indices'])
        reminder=self.hass.data.get('frame_bin_reminder')
        if reminder is not None and getattr(reminder,'manager',None) is self:
            index=reminder.data.get('slot',{}).get('index')
            if type(index) is int:indices.add(index)
        return indices

    async def oldest_stored(self,state):
        stored=state.get('9606',{}).get('value')
        if not isinstance(stored,list) or any(type(i) is not int or not 0<=i<=255 for i in stored):
            raise FrameError('Cannot verify the pictures stored on this frame; nothing was removed')
        stored=set(stored)-{0}
        items=await self.client.catalogue()
        if len(stored)<10 and len(items)<10:return None
        items={i['imageIndex']:i for i in items if i.get('imageIndex') in stored}
        eligible=stored-self.protected_indices()
        if not eligible:raise FrameError('No replaceable stored artwork was found')
        try:
            oldest=min(eligible,key=lambda i:(int(items[i]['createdAt']),i))
            created=int(items[oldest]['createdAt'])
            if created<=0:raise ValueError()
        except (KeyError,TypeError,ValueError):
            raise FrameError('Cannot establish the oldest stored picture; nothing was removed') from None
        return {'index':oldest,'created_at':created}

    async def replace_oldest(self,index,digest):
        if self.config.get('model')!='frame1' or self.connection_mode()=='local':
            raise FrameError('Oldest-picture replacement is available for original frames using Wi-Fi')
        await Replacement(self).prepare(index,digest)

    async def verify_replacement_backup(self,item):
        if not isinstance(item,dict) or not isinstance(item.get('name'),str) or Path(item['name']).name!=item['name']:
            raise FrameError('Replacement backup metadata is invalid; nothing was removed')
        path=Path(self.hass.config.path('frame_art_archive',self.frame_id,item['name']))
        content=await self.hass.async_add_executor_job(path.read_bytes)
        if hashlib.sha256(content).hexdigest()!=item.get('sha256'):
            raise FrameError('Replacement backup verification failed; nothing was removed')

    async def archive_cloud_art(self,index,items):
        item=next((i for i in items if i.get('imageIndex')==index),None)
        if not item or not item.get('mainImageUrl'):raise FrameError('Cannot back up the old picture; nothing was removed')
        content=await self.read_image(item['mainImageUrl'])
        digest=hashlib.sha256(content).hexdigest()
        name=f'{index}-{digest}.jpg'
        path=Path(self.hass.config.path('frame_art_archive',self.frame_id,name))
        def persist():
            path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            temporary=path.with_suffix('.tmp');temporary.write_bytes(content);temporary.chmod(0o600);os.replace(temporary,path)
            if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise FrameError('Picture backup verification failed; nothing was removed')
        await self.hass.async_add_executor_job(persist)
        self.data['last_archived_art']={'index':index,'name':name,'sha256':digest}
        await self.save()

    async def archived_art(self):
        item=self.data.get('last_archived_art')
        if not item or Path(item['name']).name!=item['name']:raise FrameError('No replaced-picture backup is available')
        path=Path(self.hass.config.path('frame_art_archive',self.frame_id,item['name']))
        content=await self.hass.async_add_executor_job(path.read_bytes)
        if hashlib.sha256(content).hexdigest()!=item['sha256']:raise FrameError('Picture backup verification failed')
        return content

    async def backup_current_picture(self):
        async with self.lock:
            if self.config.get('model')!='frame1':raise FrameError('Current-picture cloud backup is available for original frames')
            state=await self.client.reported_state()
            index=self.check_index(state.get('9601',{}).get('value'))
            await self.archive_cloud_art(index,await self.client.catalogue())
            self.last_action='Current picture backed up privately in Home Assistant; frame unchanged'
            self.publish('picture_backed_up')

    async def cloud_art(self,content):
        # Saved before every uncertain registration: a retry never creates an
        # additional cloud entry merely because the response was lost.
        digest=hashlib.sha256(content).hexdigest()
        ledger=self.data.setdefault('cloud_art_uploads',{})
        if digest in ledger:
            index=self.check_index(ledger[digest]);await Replacement(self).complete(digest,index);return index
        if self.data.get('pending_cloud_registration'):
            raise FrameError('An earlier cloud registration has an uncertain result; reconcile it before adding another image')
        if not self.config.get('credentials_file'):raise FrameError('SwitchBot Wi-Fi/cloud credentials are not configured')
        if self.data.get('pending_replacement'):await Replacement(self).check_ready(digest)
        if self.config.get('model')=='frame1' and self.connection_mode()!='wifi':
            # Check device capacity locally when available; check the cloud album below too.
            count=None
            try:
                async with await self.local_connection() as frame:count=len(await frame.indices())
            except (FrameError,RuntimeError,asyncio.TimeoutError):pass
            if count is not None and count>=10:
                error=FrameError('This frame already has ten stored pictures. You can replace its oldest artwork; nothing has been removed yet')
                error.replacement=await self.oldest_stored(await self.client.reported_state())
                raise error
        if self.config.get('model')=='frame1' and self.connection_mode()!='local':
            state=await self.client.reported_state()
            stored=state.get('9606',{}).get('value')
            if (isinstance(stored,list) and len({i for i in stored if type(i) is int and i>0})>=10) or len(await self.client.catalogue())>=10:
                error=FrameError('This frame or its cloud album already has ten pictures. You can replace its oldest stored artwork; nothing has been removed yet')
                error.replacement=await self.oldest_stored(state)
                raise error
        from .native_image import cloud_assets
        assets=await self.hass.async_add_executor_job(cloud_assets,content,self.config.get('model','frame2'),self.config.get('panel_size'))
        names=await self.client.upload_assets(assets)
        # Asset PUTs do not consume album slots. Recheck both capacities after
        # they finish and immediately before an irreversible registration.
        if self.data.get('pending_replacement'):await Replacement(self).check_ready(digest)
        self.data['pending_cloud_registration']={'sha256':digest,'files':names}
        if self.data.get('pending_replacement'):await self.save_verified()
        else:await self.save()
        try:
            index=self.check_index(await self.client.register_image(names))
        except FrameError as error:
            # A definite rejection can be reconciled without leaving a permanent
            # upload lock. Timeouts and unreadable responses remain uncertain.
            if getattr(error,'result_code',None) is not None:
                from urllib.parse import urlparse
                try:
                    matches=[item for item in await self.client.catalogue() if urlparse(item.get('mainImageUrl','')).path.rsplit('/',1)[-1]==names[0]]
                except Exception:
                    raise error from None
                if len(matches)==1:
                    index=self.check_index(matches[0]['imageIndex'])
                elif not matches:
                    self.data.pop('pending_cloud_registration',None);await self.save()
                    raise error
                else:raise error
            else:raise
        ledger[digest]=index;self.data.pop('pending_cloud_registration',None);await self.save()
        await Replacement(self).complete(digest,index)
        return index

    async def deliver_cloud_art(self,content):
        index=await self.cloud_art(content)
        reserved=set(self.data.get('local_art_uploads',{}).values())|set(self.data.get('baby_indices',[]))
        if self.config.get('model','frame2')=='frame2' and index in reserved:
            raise FrameError('Cloud image ID overlaps a reserved local picture; download stopped to protect existing artwork')
        await self.client.download(index,self.config.get('model','frame2'))
        self.last_transport='SwitchBot cloud / Wi-Fi';self.last_storage_verified=False
        # Wi-Fi-only mode must not use Bluetooth even for verification.
        if self.connection_mode()!='wifi':
            async with AsyncExitStack() as stack:
                try:frame=await stack.enter_async_context(await self.local_connection())
                except (FrameError,RuntimeError,asyncio.TimeoutError):frame=None
                if frame:
                    for attempt in range(30):
                        if index in await frame.indices():
                            await frame.show(index)
                            if not self.mode_matches(await frame.mode_info(),index):raise FrameError('Frame did not confirm the selected picture')
                            self.last_storage_verified=True;break
                        await asyncio.sleep(3)
                    if not self.last_storage_verified:raise FrameError('Cloud accepted the image but Bluetooth did not confirm its download; retry reuses the same cloud entry')
        if not self.last_storage_verified:
            reported=await self.client.select_downloaded(index,self.config.get('model','frame2'))
            self.data['last_cloud_storage_reported']=reported;await self.save()
            self.last_action='SwitchBot accepted the download request. Frame storage and screen are not verified.'
            self.publish('cloud_request_accepted')
        else:
            self.last_action='Wi-Fi image download confirmed and selected over Bluetooth';self.publish('art_selected')
        return {'sent':self.last_storage_verified,'accepted':True,'local_storage_verified':self.last_storage_verified,
                'display_verified':False,'cloud_storage_reported':self.data.get('last_cloud_storage_reported',False),
                'transport':self.last_transport,'cloud_upload':True}

    async def select_image(self,index):
        index=self.check_index(index)
        async with self.lock:
            frame=None
            async with AsyncExitStack() as stack:
                if self.connection_mode()!='wifi':
                    try:frame=await stack.enter_async_context(await self.local_connection())
                    except (FrameError,RuntimeError,asyncio.TimeoutError):
                        if self.connection_mode()=='local':raise
                if frame:
                    if index not in await frame.indices():raise FrameError('This image is not stored on the frame')
                    await frame.show(index)
                    if not self.mode_matches(await frame.mode_info(),index):raise FrameError('Frame did not confirm selection')
                    self.last_transport='Bluetooth';self.last_storage_verified=True
                else:
                    if self.config.get('model')=='frame1':await self.client.refresh_image(index)
                    else:await self.client.show(index,self.config.get('model','frame2'))
                    self.last_transport='SwitchBot cloud / Wi-Fi';self.last_storage_verified=False
            self.last_action='Stored picture selection requested';self.publish('art_selected' if frame else 'cloud_request_accepted')

    async def reconcile_registration(self,confirm_rejected=False):
        async with self.lock:
            pending=self.data.get('pending_cloud_registration')
            if not pending:return
            name=pending['files'][0]
            from urllib.parse import urlparse
            matches=[item for item in await self.client.catalogue() if urlparse(item.get('mainImageUrl','')).path.rsplit('/',1)[-1]==name]
            if len(matches)==1:
                self.data.setdefault('cloud_art_uploads',{})[pending['sha256']]=self.check_index(matches[0]['imageIndex'])
            elif not matches and confirm_rejected:
                pass  # Explicit operator confirmation that the registration was rejected.
            else:raise FrameError('Registration remains uncertain; no new image was added')
            self.data.pop('pending_cloud_registration',None);await self.save()
            self.last_action='Interrupted upload reconciled. Ready to send a picture.'
            self.publish('registration_reconciled')

    async def save(self): await self.store.async_save(self.data)

    async def save_verified(self):
        # Store.async_save logs some disk errors without raising. Read back via
        # the supported Store API before allowing replacement/layout mutation.
        expected=json.loads(json.dumps(self.data))
        await self.save()
        if await self.store.async_load()!=expected:
            raise FrameError('Controller state persistence was not verified; no further frame mutation was attempted')

    def waterfall_on(self):
        entity=self.config.get('waterfall_entity')
        return bool(entity and self.hass.states.is_state(entity,'on'))

    def desired(self): return not self.data.get('art_override',False) and (self.data.get('manual_baby',False) or self.waterfall_on())

    async def report_failure(self,error):
        message=str(error) if isinstance(error,FrameError) else 'Frame operation failed; check Home Assistant logs'
        self.last_action='Operation failed'
        self.last_storage_verified=False
        self.publish('error',message)
        # Deliberately do not log exception bodies, image URLs or credentials.
        await self.hass.services.async_call('persistent_notification','create',
            {'title':self.name,'message':message,
             'notification_id':DOMAIN+'_'+self.frame_id},blocking=True)

    def schedule(self):
        task=self.hass.async_create_task(self.reconcile())
        self.tasks.add(task);task.add_done_callback(self.tasks.discard)

    async def read_image(self,url):
        async with async_get_clientsession(self.hass).get(url,timeout=30) as response:
            if response.status != 200: raise FrameError('Could not read the source picture')
            chunks=[]; size=0
            async for chunk in response.content.iter_chunked(65536):
                size+=len(chunk)
                if size>MAX_FILE:raise FrameError('Source picture exceeds 8 MB')
                chunks.append(chunk)
            raw=b''.join(chunks)
        return await self.hass.async_add_executor_job(jpeg_bytes,raw)





    async def refresh_local_key(self):
        if not self.config.get('credentials_file'):raise FrameError('Online reconnect is not configured for this frame; update its private local key file after pairing')
        key=await self.client.communication_key()
        if self.config.get('_entry_id'):
            entry=self.hass.config_entries.async_get_entry(self.config['_entry_id'])
            if entry is None:raise FrameError('This frame configuration no longer exists')
            self.hass.config_entries.async_update_entry(entry,data={**entry.data,'local':{'device_id':self.client.device,'communication_key':key}})
            self.local_key=key
            return
        path=Path(self.hass.config.path(self.config.get('local_key_file','frame_local_private.json')))
        def persist():
            settings=json.loads(path.read_text())
            if settings.get('device_id')!=self.client.device:raise FrameError('Connection settings belong to a different frame')
            settings['communication_key']=key
            temporary=path.with_suffix('.json.tmp')
            temporary.write_text(json.dumps(settings));temporary.chmod(0o600);os.replace(temporary,path)
        await self.hass.async_add_executor_job(persist)
        self.local_key=key

    async def local_connection(self):
        from homeassistant.components import bluetooth
        from bleak_retry_connector import establish_connection,BleakClientWithServiceCache
        from .local_ble import LocalFrame
        if self.config.get('model')=='frame1':
            from .original_ble import OriginalFrame
            LocalFrame=OriginalFrame
        mac=':'.join(self.client.device[i:i+2] for i in range(0,12,2))
        device=bluetooth.async_ble_device_from_address(self.hass,mac,connectable=True)
        if not device:raise FrameError(self.name+' is not reachable through Home Assistant Bluetooth')
        async def connect(device):
            return await establish_connection(BleakClientWithServiceCache,device,self.name)
        @asynccontextmanager
        async def connection():
            frame=LocalFrame(device,self.local_key,connect)
            try:
                await frame.__aenter__()
                await frame.info()
            except (asyncio.TimeoutError,RuntimeError):
                if getattr(frame,'client',None) and frame.client.is_connected:await frame.client.disconnect()
                raise FrameError('Local frame connection failed. No cloud fallback was used; use Reconnect after reset if the frame was reset') from None
            try:yield frame
            finally:await frame.__aexit__(None,None,None)
        return connection()

    async def repair_connection(self):
        # Explicit setup/re-pairing action only; ordinary uploads never call this.
        async with self.lock:
            self.publish('reconnecting')
            try:
                if self.connection_mode()=='wifi':
                    await self.client.authenticate(force=True)
                    self.last_action='SwitchBot sign-in refreshed. Wi-Fi mode does not use Bluetooth.';self.publish('connection_repaired');return
                await self.refresh_local_key()
                async with await self.local_connection() as frame:
                    indices=set(await frame.indices())
                    missing=set(self.data['baby_indices'])-indices
                    if missing:
                        if len(missing)!=1:raise FrameError('Baby image tracking needs review before restoring images')
                        if self.config.get('model')=='frame1':raise FrameError('Original-frame notification image is missing; provision it through Wi-Fi mode')
                        source=await self.read_local_baby()
                        data=await self.hass.async_add_executor_job(panel_bytes,source)
                        await self.wait_native_idle(frame)
                        for index in missing:await asyncio.wait_for(frame.upload_native(index,data),180)
                        indices=set(await frame.indices())
                        if not missing.issubset(indices):raise FrameError('The frame did not confirm the restored baby picture')
                self.data['normal_indices']=sorted(indices-set(self.data['baby_indices']))
                await self.save()
                self.last_action='Connection repaired. Image list read locally; missing baby restored from local storage if needed.'
                self.publish('connection_repaired')
            except Exception as error:
                await self.report_failure(error);raise

    async def read_local_baby(self):
        path=Path(self.hass.config.path(self.config.get('baby_image_file','frame_baby_asleep.jpg')))
        try:raw=await self.hass.async_add_executor_job(path.read_bytes)
        except OSError:raise FrameError('The local baby picture source is missing; no cloud download was attempted') from None
        return await self.hass.async_add_executor_job(jpeg_bytes,raw)

    async def reconcile_local(self):
        if not self.data['baby_indices']:
            if not self.desired():
                if not self.config.get('waterfall_entity'):
                    async with await self.local_connection() as frame:
                        normal=sorted(await frame.indices())
                        if not normal:raise FrameError('No normal artwork is available')
                        await frame.normal(normal)
                        mode=bytes.fromhex(await frame.mode_info())
                        if len(mode)<2 or mode[1]!=1:raise FrameError('Frame did not confirm the normal slideshow setting')
                    self.data['normal_indices']=normal;await self.save()
                    self.last_action='Normal slideshow restored locally';self.publish('normal');return
                self.last_action='Local control ready; baby image needs one-time provisioning'
                self.publish('local_ready');return
            content=await self.read_local_baby()
            index=await self.art_index(content)
            await self.ensure_local_art(index,content)
            self.data['baby_indices']=[index];await self.save()
        async with await self.local_connection() as frame:
            indices=set(await frame.indices());baby=set(self.data['baby_indices'])
            if len(baby)!=1 or not baby.issubset(indices):
                raise FrameError('Stored local baby picture is missing. No cloud upload was attempted')
            normal=sorted(indices-baby)
            if not normal:raise FrameError('No normal artwork is available')
            self.data['normal_indices']=normal;await self.save()
            if self.desired():
                index=next(iter(baby));await frame.show(index)
                info=bytes.fromhex(await frame.mode_info())
                if not self.mode_matches(info.hex(),index):
                    raise FrameError('Frame did not confirm the local baby picture setting')
                self.last_action='Baby selected locally over Bluetooth';self.publish('baby_selected')
            else:
                await frame.normal(normal)
                info=bytes.fromhex(await frame.mode_info())
                if info[1]!=1:raise FrameError('Frame did not confirm the normal slideshow setting')
                self.last_action='Normal slideshow restored locally; stored baby excluded'
                self.publish('normal')

    async def reconcile(self):
        async with self.lock:
            try:
                self.publish('working');await self.save()
                if self.connection_mode()=='wifi':
                    await self.reconcile_cloud();return
                if self.connection_mode()=='hybrid':
                    try:
                        async with await self.local_connection() as frame:await frame.indices()
                    except (FrameError,RuntimeError,asyncio.TimeoutError):
                        await self.reconcile_cloud();return
                if not self.local_key:raise FrameError('Local Bluetooth connection is required; no cloud upload was attempted')
                if self.config.get('model')=='frame1' and self.desired() and not self.data['baby_indices']:
                    content=await self.read_local_baby()
                    result=await self.deliver_cloud_art(content)
                    if not result['local_storage_verified']:raise FrameError('Baby download requested; local storage not yet confirmed')
                    self.data['baby_indices']=[self.data['cloud_art_uploads'][hashlib.sha256(content).hexdigest()]];await self.save()
                await self.reconcile_local()
                self.last_transport='Bluetooth';self.last_storage_verified=True;self.publish()
            except Exception as error:
                await self.report_failure(error)

    async def reconcile_cloud(self):
        if not self.config.get('credentials_file'):raise FrameError('Wi-Fi/cloud credentials are not configured')
        if self.desired():
            if not self.data['baby_indices']:
                content=await self.read_local_baby();index=await self.cloud_art(content)
                self.data['baby_indices']=[index];await self.save()
                await self.client.download(index,self.config.get('model','frame2'))
                await self.client.select_downloaded(index,self.config.get('model','frame2'))
            else:await self.client.show(self.check_index(self.data['baby_indices'][0]),self.config.get('model','frame2'))
        else:
            # Cloud album entries are not proof of frame-local storage. Use the
            # saved confirmed playlist; never silently include notification art.
            normal=self.data['normal_indices']
            if not normal:raise FrameError('No confirmed normal playlist is saved; read stored pictures over Bluetooth first')
            await self.client.normal(normal,self.config.get('model','frame2'))
        self.last_transport='SwitchBot cloud / Wi-Fi';self.last_storage_verified=False
        self.last_action='SwitchBot accepted the display request; physical display is not verified.'
        self.publish('cloud_request_accepted')

    async def wait_native_idle(self,frame):
        # Match the app's preflight: byte 3 == 1 means another download is active.
        # Cloud upload registration can start that download after the album entry
        # appears, so observe a settling window as well as consecutive idle reads.
        quiet=0;transitions=[];last=None
        for attempt in range(60):
            status=await frame.command('0f7b00')
            if len(status)<4 or status[0]!=1:
                raise FrameError('Could not confirm that the frame image downloader is idle')
            state=status[3]
            if state!=last:
                transitions.append({'seconds':attempt*2,'state':state});last=state
                self.data['last_download_wait']=transitions;await self.save()
            quiet=0 if state==1 else quiet+1
            self.last_action='Waiting for the frame image downloader to finish' if state==1 else 'Checking the frame is ready for a complete local transfer'
            self.publish('waiting_for_frame')
            if attempt>=7 and quiet>=3:return
            await asyncio.sleep(2)
        raise FrameError('The frame is still downloading another picture. No Bluetooth image write was started; retry this saved picture later')

    async def ensure_local_art(self,index,content=None):
        # A catalogue bit proves allocation, not intact panel pixels. An explicit
        # send with source bytes must rewrite that same slot, including retries.
        if content is None:
            async with await self.local_connection() as frame:
                if index in await frame.indices():return
        if content is not None:
            self.publish('transferring')
            data=await self.hass.async_add_executor_job(panel_bytes,content)
            done=0;packet_size=0;stage='connect'
            def progress(sent,total,size):
                nonlocal done,packet_size
                done=sent;packet_size=size
                self.last_action=f'Sending artwork locally: {sent*100//total}%'
                self.publish('transferring')
            failures=[]
            for attempt in range(3):
                done=0;stage='connect'
                try:
                    async with await self.local_connection() as frame:
                        stage='download idle check'
                        await self.wait_native_idle(frame)
                        stage='image transfer'
                        await asyncio.wait_for(frame.upload_native(index,data,progress),180)
                        stage='final storage check'
                        if index not in await frame.indices():
                            raise FrameError('Bluetooth transfer finished but the picture was not confirmed in frame storage')
                    self.data['last_transfer']={'index':index,'attempts':attempt+1,'failures':failures,'bytes':len(data)}
                    await self.save();break
                except FrameError:raise
                except Exception as error:
                    failures.append({'stage':stage,'progress':done*100//len(data),'error':type(error).__name__})
                    self.data['last_transfer']={'index':index,'attempts':attempt+1,'failures':failures,'bytes':len(data)}
                    await self.save()
                    if attempt==2:
                        detail=str(error) if isinstance(error,RuntimeError) and str(error).startswith('Bluetooth image transfer ') else type(error).__name__
                        raise FrameError(f'Bluetooth {stage} failed after 3 attempts: {detail}. Last progress {done*100//len(data)}%, packet size {packet_size}. The same local slot is reserved for retry') from None
                    self.last_action=f'Reconnecting for local transfer attempt {attempt+2}/3; reusing the same picture slot'
                    self.publish('retrying_local_transfer');await asyncio.sleep(2)
            return
        raise FrameError('The picture is not stored locally and no local source was provided; no cloud download was attempted')

    async def art_index(self,content):
        if not self.local_key:raise FrameError('Local Bluetooth connection is required; no cloud upload was attempted')
        fingerprint=hashlib.sha256(content).hexdigest()
        async with await self.local_connection() as frame:
            present=set(await frame.indices())
        owned=self.data.setdefault('local_art_uploads',{})
        previous=self.data.get('last_art_upload',{})
        index=owned.get(fingerprint)
        if index is None and previous.get('sha256')==fingerprint and previous.get('index') in present:
            index=previous['index']
        if index is None:
            # 4093 was verified with Wi-Fi blocked and no cloud album entry.
            # Reserve before transfer so an interrupted send reuses the same slot.
            reserved=set(owned.values())|set(self.data['baby_indices'])
            index=next((i for i in range(4093,0,-1) if i not in present|reserved),None)
            if index is None:raise FrameError('No unused local image slot is available; no existing picture was overwritten')
        if not isinstance(index,int) or not 1<=index<=20480:raise FrameError('Invalid saved local image slot')
        owned[fingerprint]=index
        self.data['last_art_upload']={'sha256':fingerprint,'index':index,'transport':'Bluetooth'}
        await self.save()
        return index

    async def upload(self,raw,override_baby=False,replace_index=None,expected_layout=None):
        async with self.lock:
            if expected_layout is not None and expected_layout!=self.data.get('layout',{'orientation':'landscape','flipped':False}):
                raise FrameError('Saved frame layout changed. Refresh the preview and send again; nothing was removed')
            if self.desired() and not override_baby:raise FrameError('The baby picture is active. Confirm replacement in the dashboard to send this picture anyway')
            override_applied=bool(override_baby and self.desired())
            if override_applied:
                self.data['art_override']=True;await self.save()
            self.publish('uploading')
            try:
                content=await self.hass.async_add_executor_job(jpeg_bytes,raw)
                digest=hashlib.sha256(content).hexdigest()
                pending=self.data.get('pending_replacement')
                if pending and (pending['sha256']!=digest or replace_index not in (None,pending['index'])):
                    raise FrameError('A different replacement is pending; resume the same picture without choosing another artwork')
                if pending:replace_index=pending['index']
                if replace_index is not None:await self.replace_oldest(replace_index,digest)
                if self.connection_mode()=='wifi' or self.config.get('model')=='frame1':
                    if self.connection_mode()=='local':raise FrameError('New images on the original frame require Wi-Fi/cloud; local mode can select stored images only')
                    return await self.deliver_cloud_art(content)
                if not self.local_key:raise FrameError('Local Bluetooth connection is required; no cloud upload was attempted')
                if self.connection_mode()=='hybrid':
                    try:
                        async with await self.local_connection() as frame:await frame.indices()
                    except (FrameError,RuntimeError,asyncio.TimeoutError):return await self.deliver_cloud_art(content)
                index=await self.art_index(content)
                if self.local_key:
                    await self.ensure_local_art(index,content)
                    if self.desired():
                        self.schedule()
                        raise FrameError('Picture stored; baby notification became active, so artwork was not selected')
                    async with await self.local_connection() as frame:
                        await frame.show(index)
                        mode=bytes.fromhex(await frame.mode_info())
                        if len(mode)<4 or mode[1]!=0 or int.from_bytes(mode[2:4],'little')!=index:
                            raise FrameError('The frame did not confirm the selected artwork')
                async with await self.local_connection() as frame:
                    self.data['normal_indices']=sorted(set(await frame.indices())-set(self.data['baby_indices']))
                await self.save();self.last_transport='Bluetooth';self.last_storage_verified=True;self.last_action='Uploaded artwork selected';self.publish('art_selected')
                return {'sent':True,'local_storage_verified':True,'display_verified':False,'transport':'Bluetooth','cloud_upload':False}
            except Exception as error:
                if override_applied and self.data.get('art_override'):
                    self.data['art_override']=False;await self.save()
                await self.report_failure(error)
                raise

class FramesView(HomeAssistantView):
    url='/api/'+DOMAIN+'/frames';name='api:'+DOMAIN+':frames';requires_auth=True
    def __init__(self,registry):self.registry=registry
    async def get(self,request):
        user=request.get('hass_user')
        if not user or not user.is_admin:return web.json_response({'error':'Administrator access required'},status=403)
        return web.json_response({'frames':self.registry.descriptions()})
    async def post(self,request):
        user=request.get('hass_user')
        if not user or not user.is_admin:return web.json_response({'error':'Administrator access required'},status=403)
        try:
            value=await request.json()
            if not isinstance(value,dict):raise FrameError('Invalid frame preference')
            manager=self.registry.select(value.get('frame_id'))
            revision=value.get('expected_revision')
            if type(revision) is not int or revision<0:
                raise FrameError('Reload this dashboard before saving frame orientation')
            layout=await manager.set_layout(value.get('layout'),expected_revision=revision)
            return web.json_response({'layout':layout,'layout_revision':manager.data.get('layout_revision',0)})
        except (FrameError,ValueError) as error:
            return web.json_response({'error':str(error)},status=400)


class PrepareView(HomeAssistantView):
    url='/api/'+DOMAIN+'/prepare';name='api:'+DOMAIN+':prepare';requires_auth=True
    def __init__(self,registry):self.registry=registry;self.processing=asyncio.Semaphore(1)
    async def post(self,request):
        user=request.get('hass_user')
        if not user or not user.is_admin:return web.json_response({'error':'Administrator access required'},status=403)
        try:
            manager=self.registry.select(request.query.get('frame_id'))
            if request.content_length and request.content_length>MAX_SOURCE_FILE:return web.json_response({'error':'Choose an original picture smaller than 64 MB'},status=413)
            chunks=[];size=0
            async for chunk in request.content.iter_chunked(65536):
                size+=len(chunk)
                if size>MAX_SOURCE_FILE:return web.json_response({'error':'Choose an original picture smaller than 64 MB'},status=413)
                chunks.append(chunk)
            if not size:raise FrameError('Choose a picture first')
            bound={'7.3':800,'13.3':1600,'31.5':2560}[manager.config.get('panel_size','7.3' if manager.config.get('model')=='frame1' else '13.3')]
            async with self.processing:
                content=await manager.hass.async_add_executor_job(prepare_source,b''.join(chunks),bound)
            return web.json_response({'image':base64.b64encode(content).decode(),'bound':bound})
        except (FrameError,ValueError):return web.json_response({'error':'Could not prepare the picture. Use a JPEG, PNG or WebP of at most 64 MB and 80 megapixels.'},status=400)

class ArchiveView(HomeAssistantView):
    url='/api/'+DOMAIN+'/archive';name='api:'+DOMAIN+':archive';requires_auth=True
    def __init__(self,registry):self.registry=registry
    async def post(self,request):
        user=request.get('hass_user')
        if not user or not user.is_admin:return web.json_response({'error':'Administrator access required'},status=403)
        try:
            value=await request.json()
            if not isinstance(value,dict):raise FrameError('Invalid backup request')
            manager=self.registry.select(value.get('frame_id'))
            content=await manager.archived_art()
            return web.json_response({'image':base64.b64encode(content).decode(),'filename':manager.frame_id+'-replaced-picture.jpg'})
        except (FrameError,OSError,ValueError):return web.json_response({'error':'Could not read the replaced-picture backup'},status=400)

class UploadView(HomeAssistantView):
    url='/api/'+DOMAIN+'/upload';name='api:'+DOMAIN+':upload';requires_auth=True
    def __init__(self,registry):self.registry=registry
    async def post(self,request):
        user=request.get('hass_user')
        if not user or not user.is_admin:return web.json_response({'error':'Administrator access required'},status=403)
        if request.content_length and request.content_length>MAX_FILE*4//3+2048:
            return web.json_response({'error':'Choose an image smaller than 8 MB'},status=413)
        manager=None
        try:
            value=await request.json()
            if not isinstance(value,dict):raise FrameError('Invalid image upload')
            manager=self.registry.select(value.get('frame_id'))
            encoded=value.get('image','')
            if not isinstance(encoded,str) or len(encoded)>MAX_FILE*4//3+4:raise FrameError('Choose an image smaller than 8 MB')
            raw=base64.b64decode(encoded,validate=True)
            layout=value.get('layout')
            if not isinstance(layout,dict) or set(layout)!={'orientation','flipped'} or layout.get('orientation') not in ('portrait','landscape') or type(layout.get('flipped')) is not bool:
                raise FrameError('Reload this dashboard to use the saved frame layout before sending; nothing was removed')
            return web.json_response(await manager.upload(raw,override_baby=value.get('override_baby') is True,replace_index=value.get('replace_index'),expected_layout=layout))
        except (FrameError,binascii.Error,ValueError) as error:
            if manager:await manager.report_failure(error)
            return web.json_response({'error':str(error) if isinstance(error,FrameError) else 'Invalid image upload',**({'replacement':error.replacement} if getattr(error,'replacement',None) else {})},status=409 if getattr(error,'replacement',None) else 400)
        except Exception as error:
            if manager:await manager.report_failure(error)
            return web.json_response({'error':'Frame upload failed'},status=502)

async def load_manager(hass,settings):
    if settings.get('_entry_seed') is not None:
        manager=Manager(hass,settings,settings['_entry_seed'])
        saved=await manager.store.async_load()
        if saved:manager.data.update(saved)
        local=settings.get('_entry_local')
        manager.local_key=local['communication_key'] if local else None
        return manager
    local_path=Path(hass.config.path(settings['local_key_file']))
    local_settings=json.loads(await hass.async_add_executor_job(local_path.read_text)) if await hass.async_add_executor_job(local_path.exists) else None
    if settings.get('credentials_file'):
        path=Path(hass.config.path(settings['credentials_file']))
        seed=json.loads(await hass.async_add_executor_job(path.read_text))
    else:
        if not local_settings:raise FrameError('Configure a Bluetooth key or Wi-Fi/cloud credentials')
        seed={'device_id':local_settings['device_id'],'group_id':'','session':{'headers':{}}}
    if local_settings and local_settings.get('device_id')!=seed['device_id']:raise FrameError('Local key belongs to another frame')
    # The legacy cloud device UUID differs from the local Bluetooth device id.
    # Validate the configured identity against either its captured cloud id or BLE id.
    expected=settings['device_id'].replace(':','').lower()
    identities={str(seed.get('device_id','')).replace(':','').lower(),str(seed.get('cloud_device_id','')).lower()}
    if not settings.get('_legacy') and expected not in identities:raise FrameError('Configured device_id does not match this frame private settings')
    manager=Manager(hass,settings,seed)
    saved=await manager.store.async_load()
    if saved:manager.data.update(saved)
    manager.local_key=local_settings['communication_key'] if local_settings else None
    return manager

async def async_setup(hass,config):
    try:
        settings_list=frame_configs(config[DOMAIN]) if DOMAIN in config else []
        managers={}
        for settings in settings_list:
            manager=await load_manager(hass,settings)
            if any(m.client.device.upper()==manager.client.device.upper() for m in managers.values()):raise FrameError('The same frame is configured twice')
            managers[manager.frame_id]=manager
    except Exception:
        raise HomeAssistantError('Cannot load private frame controller configuration; check unique frame settings and matching local keys') from None
    registry=FrameRegistry(hass,managers,config.get(DOMAIN,{}).get('default_frame'));hass.data[DOMAIN]=registry
    hass.http.register_view(FramesView(registry));hass.http.register_view(UploadView(registry))
    hass.http.register_view(ArchiveView(registry))
    hass.http.register_view(PrepareView(registry))
    from .generation import GenerateView
    hass.http.register_view(GenerateView(registry))
    from .gallery import async_setup as setup_gallery
    await setup_gallery(hass,{'frame_art_gallery':{'directory':'frame_art_gallery'}})
    def target(call):
        try:return registry.select(call.data.get('frame_id'))
        except FrameError as error:raise HomeAssistantError(str(error)) from None
    async def show_baby(call):
        manager=target(call)
        async with manager.lock:
            manager.data['manual_baby']=True;manager.data['art_override']=False;await manager.save()
        await manager.reconcile()
        if manager.status=='error':raise HomeAssistantError(manager.error)
    async def restore(call):
        manager=target(call)
        async with manager.lock:
            manager.data['manual_baby']=False;manager.data['art_override']=False;await manager.save()
        if manager.desired():raise HomeAssistantError('Turn this frame’s notification switch off before restoring normal artwork')
        await manager.reconcile()
        if manager.status=='error':raise HomeAssistantError(manager.error)
    async def repair(call):await target(call).repair_connection()
    async def backup_picture(call):await target(call).backup_current_picture()
    async def set_mode(call):await target(call).set_connection_mode(call.data['mode'])
    async def set_layout(call):
        try:await target(call).set_layout({'orientation':call.data['orientation'],'flipped':call.data['flipped']})
        except FrameError as error:raise HomeAssistantError(str(error)) from None
    hass.services.async_register(DOMAIN,'set_layout',set_layout,schema=vol.Schema({
        vol.Required('frame_id'):cv.slug,vol.Required('orientation'):vol.In(['landscape','portrait']),
        vol.Required('flipped'):cv.boolean}))
    async def select_image(call):
        try:await target(call).select_image(call.data['index'])
        except FrameError as error:raise HomeAssistantError(str(error)) from None
    async def reconcile_registration(call):await target(call).reconcile_registration(call.data.get('confirm_rejected',False))
    hass.services.async_register(DOMAIN,'select_image',select_image,schema=vol.Schema({vol.Optional('frame_id'):cv.slug,vol.Required('index'):vol.Coerce(int)}))
    hass.services.async_register(DOMAIN,'reconcile_cloud_registration',reconcile_registration,schema=vol.Schema({vol.Optional('frame_id'):cv.slug,vol.Optional('confirm_rejected',default=False):cv.boolean}))
    hass.services.async_register(DOMAIN,'set_connection_mode',set_mode,schema=vol.Schema({
        vol.Optional('frame_id'):cv.slug,vol.Required('mode'):vol.In(['local','hybrid','wifi'])}))
    service_schema=vol.Schema({vol.Optional('frame_id'):cv.slug})
    hass.services.async_register(DOMAIN,'repair_connection',repair,schema=service_schema)
    hass.services.async_register(DOMAIN,'backup_current_picture',backup_picture,schema=service_schema)
    hass.services.async_register(DOMAIN,'show_baby',show_baby,schema=service_schema)
    hass.services.async_register(DOMAIN,'restore_normal',restore,schema=service_schema)
    for manager in managers.values():
        @callback
        def state_changed(event,manager=manager):
            old=event.data.get('old_state');new=event.data.get('new_state')
            if new and new.state in ('on','off') and (not old or old.state!=new.state):
                manager.data['art_override']=False
                if new.state=='off':manager.data['manual_baby']=False
                manager.schedule()
        if manager.config.get('waterfall_entity'):
            async_track_state_change_event(hass,[manager.config['waterfall_entity']],state_changed)
    @callback
    def started(event):
        for manager in managers.values():
            if manager.desired():manager.schedule()
            else:
                manager.last_action='Ready. Existing frame picture left unchanged.';manager.publish('ready')
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED,started)
    for manager in managers.values():manager.publish()
    if hasattr(hass.http,'async_register_static_paths'):
        from homeassistant.components.http import StaticPathConfig
        from homeassistant.components.frontend import add_extra_js_url
        await hass.http.async_register_static_paths([StaticPathConfig('/switchbot_frame_control/frame-upload-card.js',str(Path(__file__).parent/'frontend/frame-upload-card.js'),True)])
        add_extra_js_url(hass,'/switchbot_frame_control/frame-upload-card.js?v=0.7.0-beta.1')
    return True


async def async_setup_entry(hass,entry):
    """Add a UI-configured frame to the same explicitly routed registry."""
    registry=hass.data[DOMAIN]
    settings=dict(entry.data['settings'])
    for field in ('waterfall_entity','baby_image_file'):
        if field in entry.options:
            if entry.options[field]:settings[field]=entry.options[field]
            else:settings.pop(field,None)
    settings.update(_entry_id=entry.entry_id,_entry_seed=entry.data['seed'],_entry_local=entry.data.get('local'))
    settings['_generation']={k:entry.options.get(k,'') for k in ('cloudflare_account_id','cloudflare_api_token')}
    settings=frame_configs({'frames':[settings]})[0]
    if settings['id'] in registry.managers or any(m.client.device==settings['device_id'] for m in registry.managers.values()):
        raise HomeAssistantError('This frame is already configured')
    try:manager=await load_manager(hass,settings)
    except Exception:raise HomeAssistantError('Cannot load this frame configuration') from None
    registry.managers[manager.frame_id]=manager
    entry.runtime_data=manager
    @callback
    def changed(event):
        old=event.data.get('old_state');new=event.data.get('new_state')
        if new and new.state in ('on','off') and (not old or old.state!=new.state):
            manager.data['art_override']=False
            if new.state=='off':manager.data['manual_baby']=False
            manager.schedule()
    if settings.get('waterfall_entity'):
        entry.async_on_unload(async_track_state_change_event(hass,[settings['waterfall_entity']],changed))
    manager._loaded_options=dict(entry.options)
    async def reload_options(hass,entry):
        if dict(entry.options)!=manager._loaded_options:await hass.config_entries.async_reload(entry.entry_id)
    entry.async_on_unload(entry.add_update_listener(reload_options))
    manager.last_action='Ready. Existing frame picture left unchanged.';manager.publish('ready')
    # Restart reconciliation is handled by async_setup's started listener. An
    # entry added while HA is already running reconciles only an active switch.
    if hass.is_running and manager.desired():manager.schedule()
    return True

async def async_unload_entry(hass,entry):
    manager=entry.runtime_data
    for task in list(manager.tasks):task.cancel()
    if manager.tasks:await asyncio.gather(*list(manager.tasks),return_exceptions=True)
    hass.data[DOMAIN].managers.pop(manager.frame_id,None)
    hass.states.async_remove(manager.entity_id)
    return True
