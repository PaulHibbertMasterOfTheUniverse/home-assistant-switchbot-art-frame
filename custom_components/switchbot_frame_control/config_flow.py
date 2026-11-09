"""Guided setup: sign in, choose a frame, choose an explicit connection policy."""
import re
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .onboarding import discover_account,frame_seed
from .protocol import AppClient,FrameError

DOMAIN='switchbot_frame_control'
PASSWORD=selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))

def validate_details(details,model):
    size=details['panel_size'];mode=details['connection_mode']
    if model=='frame2' and size!='13.3':raise FrameError('Only the 13.3-inch Frame 2 is validated')
    if model=='frame1' and size not in ('7.3','13.3','31.5'):raise FrameError('Unsupported original frame size')
    if mode!='local' and not details.get('keep_cloud_login'):raise FrameError('Wi-Fi and hybrid modes require retained SwitchBot sign-in')
    if details.get('waterfall_entity') and not (details.get('use_example_image') or details.get('baby_image_file')):raise FrameError('Choose a notification picture')
    return details

class ConfigFlow(config_entries.ConfigFlow,domain=DOMAIN):
    VERSION=1
    async def async_step_user(self,user_input=None):
        errors={}
        if user_input is not None:
            try:
                self.account,self.frames=await discover_account(async_get_clientsession(self.hass),user_input['username'],user_input['password'])
                if not self.frames:return self.async_abort(reason='no_frames')
                return await self.async_step_frame()
            except FrameError:errors['base']='cannot_connect'
            except Exception:errors['base']='unknown'
        return self.async_show_form(step_id='user',data_schema=vol.Schema({
            vol.Required('username'):str,vol.Required('password'):PASSWORD}),errors=errors)

    async def async_step_frame(self,user_input=None):
        if user_input is not None:
            self.frame=next((f for f in self.frames if f['device_id']==user_input['device_id']),None)
            if self.frame is None:return self.async_abort(reason='no_frames')
            await self.async_set_unique_id(self.frame['device_id'])
            self._abort_if_unique_id_configured()
            registry=self.hass.data.get(DOMAIN)
            if registry and any(m.client.device==self.frame['device_id'] for m in registry.managers.values()):
                return self.async_abort(reason='already_configured')
            return await self.async_step_details()
        choices={f['device_id']:f"{f['name']} ({'AI Art Frame 2' if f['model']=='frame2' else 'Original AI Art Frame'})" for f in self.frames}
        return self.async_show_form(step_id='frame',data_schema=vol.Schema({vol.Required('device_id'):vol.In(choices)}))

    async def async_step_details(self,user_input=None):
        errors={};frame=self.frame
        if user_input is not None:
            try:
                details=validate_details(dict(user_input),frame['model'])
                seed=frame_seed(self.account,frame);local=None
                if details['connection_mode']!='wifi':
                    key=await AppClient(async_get_clientsession(self.hass),seed).communication_key()
                    local={'device_id':frame['device_id'],'communication_key':key}
                if not details.get('keep_cloud_login'):
                    seed={'device_id':frame['device_id'],'group_id':'','region':self.account['region'],'session':{'headers':{}}}
                fid='frame_'+frame['device_id'].lower()
                settings={'id':fid,'name':details['name'],'device_id':frame['device_id'],
                    'model':frame['model'],'panel_size':details['panel_size'],'connection_mode':details['connection_mode'],
                    'local_key_file':fid+'_private.json','status_entity':'sensor.'+fid+'_control'}
                if details.get('keep_cloud_login'):settings['credentials_file']='config_entry'
                if details.get('use_example_image'):
                    settings['baby_image_file']='custom_components/switchbot_frame_control/examples/baby-asleep.jpg'
                for field in ('waterfall_entity','baby_image_file'):
                    if details.get(field):settings[field]=details[field]
                return self.async_create_entry(title=details['name'],data={'settings':settings,'seed':seed,'local':local})
            except FrameError:errors['base']='setup_failed'
            except Exception:errors['base']='unknown'
        sizes=['13.3'] if frame['model']=='frame2' else ['7.3','13.3','31.5']
        return self.async_show_form(step_id='details',data_schema=vol.Schema({
            vol.Required('name',default=frame['name']):str,
            vol.Required('panel_size',default=sizes[0]):vol.In(sizes),
            vol.Required('connection_mode',default='local' if frame['model']=='frame2' else 'wifi'):vol.In({
                'local':'Bluetooth only','hybrid':'Prefer Bluetooth, allow SwitchBot cloud','wifi':'Wi-Fi via SwitchBot cloud'}),
            vol.Required('keep_cloud_login',default=frame['model']=='frame1'):bool,
            vol.Optional('waterfall_entity'):selector.EntitySelector(selector.EntitySelectorConfig(domain=['input_boolean','switch'])),
            vol.Optional('use_example_image',default=False):bool,
            vol.Optional('baby_image_file',default=''):str}),errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):return OptionsFlow()

class OptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self,user_input=None):
        current={**self.config_entry.data['settings'],**self.config_entry.options}
        if user_input is not None:
            return self.async_create_entry(title='',data=user_input)
        return self.async_show_form(step_id='init',data_schema=vol.Schema({
            vol.Optional('waterfall_entity',default=current.get('waterfall_entity','')):str,
            vol.Optional('baby_image_file',default=current.get('baby_image_file','')):str,
            vol.Optional('cloudflare_account_id',default=current.get('cloudflare_account_id','')):str,
            vol.Optional('cloudflare_api_token',default=current.get('cloudflare_api_token','')):PASSWORD}))
