"""Account setup without packet captures or machine-specific templates.

The client ID identifies the public mobile application; it is not a user token.
All device identities are generated for this installation. Passwords are never
trimmed, transformed, logged, or sent anywhere except SwitchBot's account host.
"""
import asyncio
import re
import uuid
from .protocol import FrameError

CLIENT_ID='pg6fbtxbi7q3o2n4zba852d5lh'
APP_VERSION='10.8'
REGIONS={'eu','us','jp','cn'}
FRAME_TYPES={'W1130000':'frame1','W1176000':'frame2'}

def login_template(installation_id=None):
    return {'request':{'clientId':CLIENT_ID,'grantType':'password','deviceInfo':{
        'deviceName':'Home Assistant','versionFlag':APP_VERSION,'appVersion':APP_VERSION,
        'deviceId':installation_id or str(uuid.uuid4()),'model':'Home Assistant'}},
        'headers':{'content-type':'application/json','appversion':APP_VERSION,
                   'user-agent':'SwitchBotFrameControl/0.6.0'}}

async def account_request(http,url,payload,headers):
    try:
        async with http.post(url,json=payload,headers=headers,timeout=30) as response:
            if response.status!=200:raise FrameError('SwitchBot account connection failed')
            result=await response.json()
        if result.get('statusCode',result.get('resultCode'))!=100:
            raise FrameError('SwitchBot sign-in or discovery failed. Check the app account login; verification-code and social-only sign-ins are not supported by this setup flow')
        body=result.get('body',result.get('data'))
        if not isinstance(body,dict):raise FrameError('SwitchBot returned an unreadable account response')
        return body
    except (asyncio.TimeoutError,OSError,ValueError,TypeError) as error:
        raise FrameError('Could not connect to SwitchBot account service') from None

async def discover_account(http,username,password):
    if not isinstance(username,str) or not username or not isinstance(password,str) or not password:
        raise FrameError('Enter your SwitchBot app email and password')
    template=login_template()
    login={'username':username,'password':password}
    auth=await account_request(http,'https://account.api.switchbot.net/account/api/v2/user/login',
                               {**template['request'],**login},template['headers'])
    token=auth.get('access_token')
    if not isinstance(token,str) or not token:raise FrameError('SwitchBot did not return an account session')
    headers={**template['headers'],'authorization':token}
    user=await account_request(http,'https://account.api.switchbot.net/account/api/v1/user/userinfo',{},headers)
    region=user.get('botRegion')
    if region not in REGIONS:raise FrameError('SwitchBot account region is not supported')
    if user.get('userID') is not None:headers['userid']=str(user['userID'])
    result=await account_request(http,f'https://wonderlabs.{region}.api.switchbot.net/wonder/device/v3/getdevice',
                                 {'required_type':'All'},headers)
    items=result.get('Items')
    if not isinstance(items,list):raise FrameError('SwitchBot device list was unreadable')
    frames=[]
    for item in items:
        if not isinstance(item,dict):continue
        detail=item.get('device_detail',{})
        if isinstance(detail,str):
            import json
            try:detail=json.loads(detail)
            except ValueError:continue
        if not isinstance(detail,dict):continue
        model=FRAME_TYPES.get(detail.get('device_type'))
        device=str(item.get('device_mac','')).replace(':','').upper()
        group=item.get('groupID')
        if model and re.fullmatch(r'[A-F0-9]{12}',device) and isinstance(group,str) and group:
            frames.append({'device_id':device,'group_id':group,'name':str(item.get('device_name') or 'Art frame'),'model':model})
    seed={'region':region,'login':login,'login_template':template,'session':{
        'headers':headers,'template':{'optSrc':'app','timeout':20000}}}
    return seed,frames

def frame_seed(account,frame):
    return {**account,'device_id':frame['device_id'],'group_id':frame['group_id']}
