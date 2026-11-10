"""Optional bin reminder with private user settings and verified original-frame cleanup."""
import asyncio
import json
import hashlib
import re
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.core import callback
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from custom_components.switchbot_frame_control.protocol import FrameError
from .schedule import collection_for

DOMAIN = 'frame_bin_reminder'
CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({
    vol.Required('frame_id'): cv.slug,
    vol.Optional('source',default='calendar'):vol.In(['calendar','erewash']),
    vol.Optional('uprn'):vol.All(cv.string,vol.Match(r'^\d{10,12}$')),
    vol.Optional('calendar_entity'):cv.entity_id,
    vol.Optional('blue_keywords',default=['blue','recycling']):vol.All(cv.ensure_list,[cv.string]),
    vol.Optional('black_keywords',default=['black','general waste','domestic waste']):vol.All(cv.ensure_list,[cv.string]),
    vol.Optional('reminder_weekday',default=1):vol.All(vol.Coerce(int),vol.Range(min=0,max=6)),
    vol.Optional('artwork_directory'):cv.string,
    vol.Optional('enabled',default=False): cv.boolean,
})}, extra=vol.ALLOW_EXTRA)

class Reminder:
    def __init__(self, hass, config):
        self.hass, self.config = hass, config
        self._prepared_assets = {}
        if config.get('source','calendar')=='erewash' and not config.get('uprn'):raise ValueError('Erewash requires your own UPRN')
        if config.get('source','calendar')=='calendar' and not config.get('calendar_entity'):raise ValueError('Choose your collection calendar entity')
        self.store = Store(hass, 1, DOMAIN + '.' + config['frame_id'])
        self.data = {}
        self.lock = asyncio.Lock()
        self.http = async_get_clientsession(hass)

    @property
    def manager(self):
        return self.hass.data['switchbot_frame_control'].select(self.config['frame_id'])

    def artwork_assets(self,kind):
        if kind not in ('blue','black','none'):raise ValueError('Unknown bin artwork')
        if self.config.get('artwork_directory'):
            base=Path(self.hass.config.path(self.config['artwork_directory'])).resolve()
            if not base.is_relative_to(Path(self.hass.config.config_dir).resolve()):raise ValueError('Artwork directory must be inside the configuration folder')
            return [base/(kind+suffix) for suffix in ('.jpg','-thumbnail.jpg','.bin')]
        from custom_components.switchbot_frame_control.native_image import cloud_assets
        from custom_components.switchbot_frame_control import __file__ as controller_file
        from PIL import Image,ImageOps
        import io
        layout=self.manager.data.get('layout',{'orientation':'landscape','flipped':False})
        key=(kind,layout.get('orientation'),bool(layout.get('flipped')))
        if key not in self._prepared_assets:
            source=Path(controller_file).parent/'examples'/(kind+'-bin.jpg')
            with Image.open(source) as im:
                portrait=layout.get('orientation')=='portrait'
                size=(1440,2560) if portrait else (2560,1440)
                image=Image.new('RGB',size,'white');fit=ImageOps.contain(im.convert('RGB'),size,Image.Resampling.LANCZOS)
                image.paste(fit,((size[0]-fit.width)//2,(size[1]-fit.height)//2))
                if layout.get('flipped'):image=image.transpose(Image.Transpose.ROTATE_180)
                if portrait:image=image.transpose(Image.Transpose.ROTATE_90)
                buf=io.BytesIO();image.save(buf,'JPEG',quality=95)
            self._prepared_assets[key]=cloud_assets(buf.getvalue(),'frame1','31.5')
        return self._prepared_assets[key]

    def read_artwork(self,kind):
        assets=self.artwork_assets(kind)
        return [item.read_bytes() if isinstance(item,Path) else item for item in assets]

    def publish(self, state, error=None):
        self.hass.states.async_set('sensor.frame_bin_reminder_'+self.config['frame_id'], state, {
            'friendly_name': 'Frame bin reminder', 'icon': 'mdi:delete',
            'frame_id': self.config['frame_id'], 'error': error,
            'collection': self.data.get('collection'),
            'collection_date': self.data.get('collection_date'),
            'checked_at': self.data.get('checked_at'),
            'restore_pending': bool(self.data.get('snapshot')),
            'restore_index': self.data.get('snapshot',{}).get('index'),
            'restore_deadline': self.data.get('snapshot',{}).get('deadline'),
            'restore_requested': self.data.get('snapshot',{}).get('restore_requested',False),
            'cleanup_verification': self.data.get('cleanup_verification'),
            'frame_diagnostics': self.data.get('frame_diagnostics'),
            'refresh_trace': getattr(self.manager.client,'last_refresh',self.data.get('last_refresh')),
            'asset_uploads': self.data.get('asset_uploads'),
            'notification_index': self.data.get('slot', {}).get('index'),
            'transport': 'Wi-Fi / SwitchBot cloud',
            'display_verified': False,
            'enabled': self.data.get('enabled',self.config.get('enabled',False)),
        })

    async def save(self):
        await self.store.async_save(self.data)

    async def record_refresh(self,details):
        self.data['last_refresh'] = json.loads(json.dumps(details))
        await self.save()
        self.publish('restoring' if self.data.get('snapshot',{}).get('restore_requested') else 'sending')

    async def inspect_frame(self,kind='black'):
        """Read shadow, catalogue and the three current assets without frame commands."""
        async with self.lock, self.manager.lock:
            state = await self.manager.client.reported_state()
            catalogue = await self.manager.client.catalogue()
            slot = self.data.get('slot',{})
            item = next((row for row in catalogue if row.get('imageIndex') == slot.get('index')),{})
            assets = await self.hass.async_add_executor_job(self.read_artwork,kind)
            checks = {}
            for number, (label,field,raw) in enumerate(zip(
                    ('main','thumbnail','bin'),('mainImageUrl','thumbnailImageUrl','ditheringImageUrl'),assets)):
                url = item.get(field,'')
                parsed = urlparse(url)
                result = {'local_bytes':len(raw),'local_sha256':hashlib.sha256(raw).hexdigest(),
                          'target_name':slot.get('names',[None]*3)[number],
                          'catalogue_name':parsed.path.rsplit('/',1)[-1] if parsed.path else None}
                result['target_matches_catalogue'] = result['target_name'] == result['catalogue_name'] if url else None
                result['asset_url_source'] = 'catalogue' if url else None
                if not url and label=='bin' and result['target_name']:
                    main = urlparse(item.get('mainImageUrl',''))
                    url = main._replace(path=main.path.rsplit('/',1)[0]+'/'+result['target_name']).geturl()
                    parsed = urlparse(url)
                    result['asset_url_source'] = 'sibling_from_main_not_catalogue_verified'
                if parsed.scheme=='https' and parsed.hostname and parsed.hostname.endswith(('.amazonaws.com','.switchbot.net','.cloudfront.net')):
                    try:
                        async with self.http.get(url,timeout=30) as response:
                            result['cloud_http_status'] = response.status
                            if response.status==200:
                                content = bytearray()
                                async for chunk in response.content.iter_chunked(65536):
                                    content.extend(chunk)
                                    if len(content)>8*1024*1024:
                                        break
                                if len(content)>8*1024*1024:
                                    result['cloud_error'] = 'Asset exceeds diagnostic size bound'
                                else:
                                    result.update(cloud_bytes=len(content),cloud_sha256=hashlib.sha256(content).hexdigest(),
                                                  cloud_matches_local=content==raw)
                    except Exception as error:
                        result['cloud_error'] = type(error).__name__
                else:
                    result['cloud_error'] = 'No supported HTTPS asset URL in catalogue'
                checks[label] = result
            self.data['frame_diagnostics'] = {
                'checked_at':dt_util.now().isoformat(),'kind':kind,
                'selected_index':state.get('9601',{}).get('value'),
                'stored_indices':state.get('9606',{}).get('value'),
                'mode':state.get('9603',{}).get('value'),
                'cloud_indices':sorted(row['imageIndex'] for row in catalogue),
                'slot_metadata':{key:item[key] for key in ('imageIndex','status','angle','imageStatus') if key in item},
                'catalogue_field_names':sorted(item),'assets':checks,
            }
            if getattr(self.manager.client,'last_refresh',None):
                self.data['last_refresh'] = self.manager.client.last_refresh
            await self.save()
            self.publish('inspected')

    async def refresh(self, target=None):
        target = target or (dt_util.now().date()+timedelta(days=1))
        if self.config.get('source','calendar')=='erewash':
            url='https://www.erewash.gov.uk/bbd-whitespace/one-year-collection-dates-without-christmas'
            async with self.http.get(url,params={'uprn':self.config['uprn']},timeout=40) as response:
                response.raise_for_status();payload=await response.json(content_type=None)
            result=collection_for(payload,target)
        else:
            from .schedule import collection_from_events
            entity=self.config['calendar_entity']
            current=self.hass.states.get(entity)
            if current is None or current.state in ('unknown','unavailable'):
                raise ValueError('Collection calendar is unavailable; no bin picture was guessed')
            start=dt_util.start_of_local_day(dt_util.now()).replace(year=target.year,month=target.month,day=target.day)
            response=await self.hass.services.async_call('calendar','get_events',
                {'entity_id':entity,'start_date_time':start.isoformat(),'end_date_time':(start+timedelta(days=1)).isoformat()},blocking=True,return_response=True)
            events=response.get(entity,{}).get('events') if isinstance(response,dict) else None
            result=collection_from_events(events,self.config.get('blue_keywords',['blue','recycling']),self.config.get('black_keywords',['black','general waste','domestic waste']))
        self.data.update(collection=result, collection_date=target.isoformat(), checked_at=dt_util.now().isoformat())
        await self.save()
        self.publish('schedule_checked')
        return result

    async def put_assets(self, names, kind):
        assets = await self.hass.async_add_executor_job(self.read_artwork,kind)
        if len(assets[2]) != 1843200:
            raise HomeAssistantError('Bin artwork has the wrong frame format')
        self.data['asset_uploads'] = []
        for number, (name, raw) in enumerate(zip(names, assets), 1):
            if not re.fullmatch(r'(main|thumbnail|bin)_[a-f0-9]{32}\.(jpg|bin)', name):
                raise HomeAssistantError('Unexpected notification asset name')
            upload = {'filename':name,'file_type':number,'bytes':len(raw),
                      'sha256':hashlib.sha256(raw).hexdigest(),'content_type':'text/plain',
                      'started_at':dt_util.now().isoformat(),'stage':'request_upload_url'}
            self.data['asset_uploads'].append(upload)
            await self.save()
            result = await self.manager.client.post('/device/artframe/api/v1/images/getUploadUrl', {
                'deviceID': self.manager.client.device, 'groupID': self.manager.client.group,
                'filename': name, 'fileType': number})
            url = result.get('uploadUrl', '')
            parsed = urlparse(url)
            if parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.amazonaws.com'):
                raise HomeAssistantError('Unexpected SwitchBot image destination')
            upload['stage'] = 'put_asset'
            await self.save()
            async with self.http.put(url, data=raw, headers={'Content-Type':'text/plain'}, timeout=90) as response:
                upload.update(http_status=response.status,finished_at=dt_util.now().isoformat(),stage='put_complete')
                await self.save()
                if response.status != 200:
                    raise HomeAssistantError('Bin artwork upload failed')

    async def provision(self, kind):
        slot = self.data.get('slot')
        if slot and slot.get('index'):
            catalogue = await self.manager.client.catalogue()
            if slot['index'] not in {item['imageIndex'] for item in catalogue}:
                raise HomeAssistantError('Notification slot was deleted; repair it before sending')
            return slot
        if slot:
            # Reconcile a lost registration response by the unique filename.
            matches = [item for item in await self.manager.client.catalogue()
                       if urlparse(item.get('mainImageUrl','')).path.rsplit('/',1)[-1] == slot['names'][0]]
            if len(matches) == 1:
                slot['index'] = matches[0]['imageIndex']; await self.save(); return slot
            raise HomeAssistantError('Earlier notification registration is uncertain; no duplicate will be created')
        state = await self.manager.client.reported_state()
        stored = state.get('9606',{}).get('value',[])
        # Original-frame shadow lists can retain a deleted cloud entry. The
        # cloud album is checked here; download failure remains a real error.
        if len(await self.manager.client.catalogue()) >= 10:
            raise HomeAssistantError('No free notification slot; no original picture has been removed')
        import uuid
        identifier = uuid.uuid4().hex
        slot = {'names':[f'main_{identifier}.jpg',f'thumbnail_{identifier}.jpg',f'bin_{identifier}.bin']}
        await self.put_assets(slot['names'],kind)
        self.data['slot'] = slot; await self.save()
        try:
            slot['index'] = await self.manager.client.register_image(slot['names'])
        except Exception:
            # Keep journal for reconciliation; never blindly register twice.
            raise
        await self.save()
        return slot

    async def show(self, kind=None, test=False, manual=False, restore_index=None, force_upload=False):
        async with self.lock, self.manager.lock:
            if self.manager.config.get('model') != 'frame1' or self.manager.config.get('panel_size') != '31.5':
                raise HomeAssistantError('This reminder is configured for the original 31.5-inch frame')
            if self.manager.connection_mode() == 'local':
                raise HomeAssistantError('Original-frame bin delivery requires Wi-Fi/cloud mode')
            now = dt_util.now()
            if kind is None:
                if now.weekday() != self.config.get('reminder_weekday',1) or not (16 <= now.hour < 20) or (now.hour == 19 and now.minute >= 30):
                    raise HomeAssistantError('Scheduled bin display is outside the configured reminder day 16:00–19:30')
                kind = await self.refresh(now.date()+timedelta(days=1))
            if kind not in ('blue','black','none'):
                raise HomeAssistantError('Unknown bin artwork')
            if not self.data.get('snapshot'):
                state = await self.manager.client.reported_state()
                index = state.get('9601',{}).get('value')
                stored = state.get('9606',{}).get('value')
                if type(index) != int or not isinstance(stored,list) or index not in stored:
                    raise HomeAssistantError('Cannot confirm the current picture to restore later')
                slot_index = self.data.get('slot',{}).get('index')
                if manual and restore_index is not None:
                    if type(restore_index) is not int or restore_index not in stored or restore_index == slot_index:
                        raise HomeAssistantError('Explicit original picture must be stored and different from the notification')
                    index = restore_index
                if index == slot_index:
                    raise HomeAssistantError('Current picture is the notification and there is no saved original')
                deadline = now + timedelta(minutes=10) if test else now.replace(hour=19,minute=30,second=0,microsecond=0)
                if manual and not test:
                    deadline = (now + timedelta(days=(self.config.get('reminder_weekday',1)-now.weekday())%7)).replace(hour=19,minute=30,second=0,microsecond=0)
                    if deadline <= now:
                        deadline += timedelta(days=7)
                self.data['snapshot'] = {'index':index,'mode':state.get('9603',{}).get('value'),
                                         'deadline':deadline.isoformat(),'created':now.isoformat(),'test':test,'manual':manual}
                await self.save()
            self.publish('sending')
            slot = await self.provision(kind)
            if force_upload or self.data.get('slot_kind') != kind or self.data.get('artwork_revision') != str(self.manager.data.get('layout',{})):
                await self.put_assets(slot['names'],kind)
            # Refresh even for unchanged artwork: a stored index may be a stale cache entry.
            await self.manager.client.refresh_image(slot['index'],trace=self.record_refresh)
            for attempt in range(40):
                state = await self.manager.client.reported_state()
                if state.get('9601',{}).get('value') == slot['index']:
                    break
                if attempt in (4,9,14,24,34):
                    await self.manager.client.show(slot['index'],'frame1')
                await asyncio.sleep(3)
            else:
                raise HomeAssistantError('Frame has not confirmed selecting the bin artwork; restoration remains scheduled')
            self.data['slot_kind'] = kind
            self.data['artwork_revision'] = str(self.manager.data.get('layout',{}))
            await self.save()
            if not test and not manual:
                self.data['last_display_window']=now.date().isoformat();await self.save()
            self.publish('display_requested')

    async def wait_released(self,index):
        for _ in range(30):
            state = await self.manager.client.reported_state()
            stored = state.get('9606',{}).get('value')
            if isinstance(stored,list) and index not in stored:
                return state
            await asyncio.sleep(3)
        raise HomeAssistantError('Notification is still stored on the frame; cleanup remains pending')

    async def restore(self):
        async with self.lock, self.manager.lock:
            snapshot = self.data.get('snapshot')
            if not snapshot:
                self.publish('ready'); return
            index = snapshot['index']
            slot_index = self.data.get('slot',{}).get('index')
            if type(slot_index) is not int or not 1 <= slot_index <= 255 or slot_index == index:
                raise HomeAssistantError('Cannot safely identify a separate notification slot; restoration remains pending')
            snapshot['restore_requested'] = True
            await self.save()
            self.publish('restoring')
            state = await self.manager.client.reported_state()
            catalogue = await self.manager.client.catalogue()
            cloud_before = {item['imageIndex'] for item in catalogue}
            if index not in cloud_before:
                raise HomeAssistantError('Previous picture is missing from the cloud album; restoration remains pending')
            stored = state.get('9606',{}).get('value')
            if not (state.get('9601',{}).get('value') == index and isinstance(stored,list) and index in stored):
                await self.manager.client.refresh_image(index,trace=self.record_refresh)
                state = await self.manager.client.reported_state()
            # Preserve the exact selected image; do not substitute a default slideshow.
            for _ in range(40):
                stored = state.get('9606',{}).get('value')
                if state.get('9601',{}).get('value') == index and isinstance(stored,list) and index in stored:
                    break
                await asyncio.sleep(3)
                state = await self.manager.client.reported_state()
            else:
                raise HomeAssistantError('Previous picture selection not yet confirmed; retry remains pending')
            if slot_index in stored:
                await self.manager.client.invoke(9609)
                await asyncio.sleep(5)
                await self.manager.client.invoke(9601,{'0':2,'1':slot_index})
                state = await self.wait_released(slot_index)
            if state.get('9601',{}).get('value') != index:
                raise HomeAssistantError('Original picture selection changed during cleanup; restoration remains pending')
            cloud_after = {item['imageIndex'] for item in await self.manager.client.catalogue()}
            if cloud_before != cloud_after:
                raise HomeAssistantError('Cloud album changed during cleanup; restoration record retained')
            self.data['cleanup_verification'] = {
                'checked_at': dt_util.now().isoformat(),
                'selected_index': index,
                'removed_device_index': slot_index,
                'stored_indices': state['9606']['value'],
                'cloud_indices': sorted(cloud_after),
                'notification_cloud_retained': slot_index in cloud_after,
                'all_other_cloud_images_stored': (cloud_before-{slot_index}).issubset(state['9606']['value']),
            }
            self.data.pop('snapshot',None);await self.save();self.publish('restored')

    async def run(self, operation, **kwargs):
        try:
            await getattr(self,operation)(**kwargs)
        except Exception as error:
            # Never expose signed URLs, request headers, or login details.
            message = str(error) if isinstance(error,(ValueError,HomeAssistantError,FrameError)) else type(error).__name__
            self.publish('error',message)
            from homeassistant.components.persistent_notification import async_create
            async_create(self.hass, 'The bin frame reminder needs attention: '+message,
                         'Bin frame reminder', DOMAIN)
            raise HomeAssistantError(message) from None

    async def tick(self, now):
        if self.lock.locked():
            return
        snapshot = self.data.get('snapshot')
        if snapshot and (snapshot.get('restore_requested') or now >= dt_util.parse_datetime(snapshot['deadline'])):
            await self.run('restore')
        elif (self.data.get('enabled',self.config.get('enabled',False)) and now.weekday()==self.config.get('reminder_weekday',1)
              and 16*60 <= now.hour*60+now.minute < 19*60+30
              and self.data.get('last_display_window') != now.date().isoformat()
              and (not snapshot or (not snapshot.get('test') and now.minute%5==0))):
            await self.run('show')

async def async_setup(hass, config):
    if DOMAIN not in config:return True
    reminder = Reminder(hass,config[DOMAIN]); reminder.data = await reminder.store.async_load() or {}
    hass.data[DOMAIN] = reminder
    async def service(call):
        if call.service == 'set_enabled':
            reminder.data['enabled']=call.data['enabled'];await reminder.save()
            reminder.publish('ready' if call.data['enabled'] else 'disabled');return
        args = {}
        if call.service == 'inspect_frame':args={'kind':call.data.get('kind','black')}
        if call.service == 'test_picture':args={'kind':call.data['kind'],'test':True}
        if call.service == 'display_picture':args={'kind':call.data['kind'],'manual':True,'restore_index':call.data.get('restore_index'),'force_upload':call.data.get('force_upload',False)}
        await reminder.run({'test_picture':'show','display_picture':'show','restore':'restore','refresh':'refresh','inspect_frame':'inspect_frame'}[call.service],**args)
    hass.services.async_register(DOMAIN,'inspect_frame',service,schema=vol.Schema({vol.Optional('kind',default='black'):vol.In(['blue','black','none'])}))
    hass.services.async_register(DOMAIN,'test_picture',service,schema=vol.Schema({vol.Required('kind'):vol.In(['blue','black','none'])}))
    hass.services.async_register(DOMAIN,'display_picture',service,schema=vol.Schema({
        vol.Required('kind'):vol.In(['blue','black','none']),
        vol.Optional('restore_index'):vol.All(vol.Coerce(int),vol.Range(min=1,max=255)),
        vol.Optional('force_upload',default=False):cv.boolean,
    }))
    hass.services.async_register(DOMAIN,'restore',service,schema=vol.Schema({}))
    hass.services.async_register(DOMAIN,'refresh',service,schema=vol.Schema({}))
    hass.services.async_register(DOMAIN,'set_enabled',service,schema=vol.Schema({vol.Required('enabled'):cv.boolean}))
    async_track_time_change(hass,reminder.tick,minute='*',second=0)
    @callback
    def started(event):
        hass.async_create_task(reminder.tick(dt_util.now()))
    if hass.is_running:hass.async_create_task(reminder.tick(dt_util.now()))
    else:hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED,started)
    reminder.publish('ready' if reminder.data.get('enabled',config[DOMAIN].get('enabled',False)) else 'disabled')
    return True
