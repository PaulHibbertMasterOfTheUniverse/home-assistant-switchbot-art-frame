"""SwitchBot app protocol. Scoped to one configured frame; secrets never logged."""
import asyncio
import base64
import json
import time
import uuid

class FrameError(Exception):
    """A request failed without exposing response bodies or credentials."""

class AppClient:
    def __init__(self, http, seed):
        self.http = http
        self.seed = seed
        self.headers = dict(seed['session']['headers'])
        region=seed.get('region','eu')
        if region not in ('eu','us','jp','cn'):raise FrameError('Unsupported SwitchBot account region')
        self.base = f'https://wonderlabs.{region}.api.switchbot.net'
        self.device = seed['device_id']
        self.group = seed['group_id']
        self.auth_lock = asyncio.Lock()

    async def authenticate(self, force=False):
        async with self.auth_lock:
            try:
                part = self.headers['authorization'].split('.')[1]
                expiry = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))['exp']
            except (KeyError, ValueError, IndexError):
                expiry = 0
            if not force and expiry > time.time() + 120:
                return
            if not self.seed.get('login_template') or not self.seed.get('login'):
                raise FrameError('SwitchBot cloud sign-in is not configured')
            t = self.seed['login_template']
            payload = {**t['request'], **self.seed['login']}
            async with self.http.post('https://account.api.switchbot.net/account/api/v2/user/login',
                    json=payload, headers=t['headers'], timeout=30) as response:
                if response.status != 200:
                    raise FrameError(f'SwitchBot sign-in HTTP {response.status}')
                result = await response.json()
            token = result.get('body', {}).get('access_token')
            if result.get('statusCode') != 100 or not token:
                raise FrameError('SwitchBot sign-in failed')
            self.headers['authorization'] = token

    async def post(self, path, payload, _renewed=False):
        await self.authenticate()
        headers = {k:v for k,v in self.headers.items()
                   if k.lower() not in ('content-length','accept-encoding','requestid')}
        if 'requestID' in payload:
            headers['requestid'] = payload['requestID']
        try:
            async with self.http.post(self.base+path, json=payload, headers=headers, timeout=35) as response:
                if response.status in (401,403) and not _renewed:
                    await self.authenticate(force=True)
                    return await self.post(path,payload,_renewed=True)
                if response.status != 200:
                    raise FrameError(f'SwitchBot HTTP {response.status}')
                result = await response.json()
        except (asyncio.TimeoutError, OSError) as error:
            raise FrameError('SwitchBot request timed out; outcome may be pending') from error
        # On image registration, 191 is also returned for a full cloud album.
        # A login refresh cannot fix that rejection and must not repeat the save.
        if result.get('resultCode') == 191 and path!='/device/artframe/api/v1/images/save' and not _renewed:
            await self.authenticate(force=True)
            return await self.post(path,payload,_renewed=True)
        if result.get('resultCode') != 100:
            error=FrameError('SwitchBot rejected request; code '+str(result.get('resultCode')))
            error.result_code=result.get('resultCode')
            raise error
        return result.get('data')

    async def communication_key(self):
        await self.authenticate()
        try:
            async with self.http.post(self.base+'/wonder/keys/v1/communicate',
                    json={'device_mac':self.device,'keyType':'user'},headers=self.headers,timeout=30) as response:
                if response.status!=200:raise FrameError('Could not refresh the frame connection key')
                result=await response.json()
            data=result.get('body',result.get('data',{}))
            key=data.get('communicationKey',{})
            if len(bytes.fromhex(key.get('key','')))!=16 or len(bytes.fromhex(key.get('keyId','')))!=1:
                raise ValueError('Invalid key')
            return {'key':key['key'],'keyId':key['keyId']}
        except (ValueError,TypeError,AttributeError,KeyError,asyncio.TimeoutError,OSError):
            raise FrameError('Could not refresh the frame connection key; check SwitchBot sign-in and try Reconnect after reset') from None

    async def catalogue(self):
        images=[];token='';seen=set()
        while True:
            data = await self.post('/device/artframe/api/v1/images/page',
                {'deviceID':self.device,'groupID':self.group,'pageSize':200,'pageToken':token})
            images.extend(data.get('images',[]))
            token=data.get('nextPageToken')
            if not token: return images
            if token in seen: raise FrameError('SwitchBot repeated a catalogue page')
            seen.add(token)

    async def invoke(self, function, params=None):
        body = {k:v for k,v in self.seed['session']['template'].items()
                if k not in ('params','requestID','functionID')}
        body.update(deviceID=self.device,functionID=function,requestID=str(uuid.uuid4()).upper())
        if params is not None: body['params']=params
        # Acceptance is not a device acknowledgement. Caller must verify separately.
        return await self.post('/command/cmd/api/v1/func/invoke',body)

    async def show(self, index, model='frame2'):
        if model=='frame1':
            await self.invoke(9602,{'0':index})
            return
        await self.invoke(9626,{'0':index,'1':0,'2':0})
        await self.invoke(9622,{'0':index})

    async def refresh_image(self,index,trace=None):
        """Refresh one original-frame device copy, retaining its cloud artwork."""
        self.last_refresh={'index':index,'started_at':time.time(),'events':[]}
        async def note(stage,**details):
            self.last_refresh['stage']=stage
            self.last_refresh['events'].append({'at':time.time(),'stage':stage,**details})
            if trace:
                await trace(self.last_refresh)
        async def observe(state):
            selected=state.get('9601',{}).get('value')
            stored=state.get('9606',{}).get('value')
            if (selected,stored)!=(self.last_refresh.get('selected_index'),self.last_refresh.get('stored_indices')):
                await note('shadow_report',selected_index=selected,stored_indices=stored)
            self.last_refresh.update(selected_index=selected,stored_indices=stored,last_checked_at=time.time())
            return stored
        if type(index) is not int or not 1<=index<=255:
            raise FrameError('Invalid original-frame image index')
        await note('catalogue_preflight')
        images=await self.catalogue()
        if not isinstance(images,list) or not any(isinstance(item,dict) and item.get('imageIndex')==index for item in images):
            raise FrameError('Picture is not in the cloud album; device copy left unchanged')
        stored=await observe(await self.reported_state())
        if not isinstance(stored,list):
            await note('initial_storage_unknown')
            raise FrameError('Cannot verify device storage before refresh; device copy left unchanged')
        if index in stored:
            await note('wake_before_release',function=9609)
            await self.invoke(9609)
            await asyncio.sleep(5)
            await note('device_release',function=9601,params={'0':2,'1':index})
            await self.invoke(9601,{'0':2,'1':index})
            for _ in range(30):
                stored=await observe(await self.reported_state())
                if isinstance(stored,list) and index not in stored:
                    break
                await asyncio.sleep(3)
            else:
                await note('release_timeout')
                raise FrameError('Frame has not confirmed releasing the picture; download not attempted')
            await note('release_confirmed')
        else:
            await note('already_absent_release_skipped')
        for download_attempt in range(1,3):
            await note('wake_before_download',attempt=download_attempt,function=9609)
            await self.invoke(9609)
            await asyncio.sleep(5)
            await note('download_request',attempt=download_attempt,function=9601,params={'0':1,'1':index})
            await self.invoke(9601,{'0':1,'1':index})
            await note('download_request_accepted',attempt=download_attempt)
            for _ in range(40):
                state=await self.reported_state()
                stored=await observe(state)
                if isinstance(stored,list) and index in stored:
                    break
                await asyncio.sleep(3)
            else:
                await note('download_presence_timeout',attempt=download_attempt)
                if download_attempt<2:
                    await note('download_retry_backoff',seconds=10)
                    await asyncio.sleep(10)
                continue
            await note('storage_confirmed',attempt=download_attempt)
            break
        else:
            await note('download_failed_after_two_attempts')
            raise FrameError('Frame has not confirmed storing the refreshed picture after two bounded download attempts; selection not attempted')
        await note('settling_before_selection',seconds=10)
        await asyncio.sleep(10)
        await note('selection_request',function=9602,params={'0':index})
        await self.show(index,'frame1')
        await note('selection_request_accepted_not_physical_confirmation')

    async def normal(self, indices, model='frame2'):
        if not indices: raise FrameError('No normal artwork remains to restore')
        if len(indices)==1: return await self.show(indices[0],model)
        if len(indices)>200: raise FrameError('Normal playlist exceeds the verified 200-image command limit')
        if model=='frame1':
            if len(indices)>10 or any(type(i) is not int or not 1<=i<=255 for i in indices):raise FrameError('Invalid original-frame playlist')
            return await self.invoke(9605,{'0':30,'1':indices})
        await self.invoke(9627,{'0':30,'1':0,'2':1440,'3':127,'4':indices})

    async def remove(self, indices):
        if not indices: return
        if any(not isinstance(i,int) or i<1 or i>20480 for i in indices):
            raise FrameError('Invalid targeted image index')
        for offset in range(0,len(indices),200):
            batch=indices[offset:offset+200]
            await self.invoke(9625,{'0':len(batch),'1':batch})
        # Exact app sequence; never call the delete-all function 9624.
        await self.post('/device/artframe/api/v1/images/delete',
            {'deviceID':self.device,'groupID':self.group,'imageIndexList':indices,'deleteAll':False})
        await self.post('/productbiz/v1/slideshow/syncDeletedImages',
            {'deviceID':self.device,'groupID':self.group,'imageIndexes':indices,'deleteAll':False})
        remaining={i['imageIndex'] for i in await self.catalogue()}
        if remaining.intersection(indices): raise FrameError('Picture removal is not yet confirmed in the catalogue')

    async def upload_assets(self,assets):
        names=[];identifier=uuid.uuid4().hex
        for number,(label,extension,data) in enumerate(zip(('main','thumbnail','bin'),('jpg','jpg','bin'),assets),1):
            name=f'{label}_{identifier}.{extension}'
            result=await self.post('/device/artframe/api/v1/images/getUploadUrl',
                {'deviceID':self.device,'groupID':self.group,'filename':name,'fileType':number})
            url=result.get('uploadUrl','')
            # Do not send artwork to an arbitrary URL returned by an unexpected
            # server response; signed upload links and bodies are never logged.
            from urllib.parse import urlparse
            parsed=urlparse(url)
            if parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith('.amazonaws.com'):
                raise FrameError('SwitchBot returned an unexpected image upload destination')
            async with self.http.put(url,data=data,headers={'Content-Type':'text/plain'},timeout=60) as response:
                if response.status!=200:raise FrameError('SwitchBot image asset upload failed')
            names.append(name)
        return names

    async def register_image(self,names):
        result=await self.post('/device/artframe/api/v1/images/save',
            {'deviceID':self.device,'groupID':self.group,'mainImage':names[0],'thumbnailImage':names[1],
             'ditheringImage':names[2],'angle':90,'fileTitle':'','fileDesc':'','imageUniqueId':'',
             'metaData':{'needLowBrightnessAlert':False,'createMethod':''}})
        index=result.get('imageIndex')
        if type(index) is not int:raise FrameError('SwitchBot did not return an image index; registration may be pending')
        return index

    async def download(self,index,model='frame2'):
        if model=='frame1':
            await self.invoke(9609)
            await self.invoke(9601,{'0':1,'1':index})
        else:
            await self.invoke(9623,{'0':1,'1':[index]})

    async def reported_state(self):
        return await self.post('/device/device/v1/shadow/getByIDs',
            {'deviceID':self.device,'propertyIDs':[9601,9603,9606]})

    async def select_downloaded(self,index,model='frame2'):
        # A cloud acknowledgement alone is not delivery. Poll the device-reported
        # storage field, never the cloud album, before requesting selection.
        if model=='frame2':
            # Frame 2 does not expose the original's 9606 storage list. Queue
            # selection after the download, without claiming device delivery.
            await self.show(index,model)
            return False
        for attempt in range(30):
            state=await self.reported_state()
            stored=state.get('9606',{}).get('value')
            if isinstance(stored,list) and index in stored:
                await self.show(index,model)
                return True
            await asyncio.sleep(3)
        return False
