"""Experimental authenticated SwitchBot Art Frame 2 BLE transport.
Adapted protocol from sblibs/pySwitchbot (MIT) and SwitchBot's device module.
No HTTP or cloud fallback. Responses use firmware's truncated GCM tag.
"""
import asyncio
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
from bleak import BleakClient
RX='cba20003-224d-11e6-9fb8-0002a5d5c51b';TX='cba20002-224d-11e6-9fb8-0002a5d5c51b'
def crc16(data):
 crc=0xffff
 for byte in data:
  crc^=byte
  for _ in range(8):crc=(crc>>1)^0xa001 if crc&1 else crc>>1
 return crc&0xffff

def transfer_packet(phase,metadata):
 raw=bytes.fromhex('570000000f7a10')+bytes([phase])+len(metadata).to_bytes(2,'big')+metadata
 return raw+crc16(raw).to_bytes(2,'big')

class LocalFrame:
 def __init__(self,device,key,connector=None):self.connector=connector;self.device=device;self.key=bytes.fromhex(key['key']);self.key_id=bytes.fromhex(key['keyId']);self.lock=asyncio.Lock()
 async def __aenter__(self):
  self.q=asyncio.Queue()
  if self.connector:self.client=await self.connector(self.device)
  else:self.client=BleakClient(self.device,timeout=20);await self.client.connect()
  await self.client.start_notify(RX,lambda _,b:self.q.put_nowait(bytes(b)))
  try:
   r=await self.raw(b'\x57\0\0\0\x0f\x21\x03'+self.key_id)
   if len(r)<8 or r[0]!=1 or r[2] not in (0,1):raise RuntimeError('Bluetooth authentication rejected')
   self.mode=r[2];self.iv=r[4:-4] if self.mode else r[4:]
   if len(self.iv)!=(12 if self.mode else 16):raise RuntimeError('Invalid Bluetooth nonce')
   return self
  except BaseException:
   await self.client.disconnect();raise
 async def __aexit__(self,*args):await self.client.disconnect()
 async def raw(self,data):
  size=getattr(self,'_transfer_write_size',None) or min(244,self.client.services.get_characteristic(TX).max_write_without_response_size)
  for offset in range(0,len(data),size):
   await self.client.write_gatt_char(TX,data[offset:offset+size],response=False)
   if len(data)>size:await asyncio.sleep(0.001)
  return await asyncio.wait_for(self.q.get(),getattr(self,'_transfer_ack_timeout',20))
 async def transfer_size(self):
  characteristic=self.client.services.get_characteristic(TX)
  limit=characteristic.max_write_without_response_size
  if limit<=20:
   backend=getattr(self.client,'_backend',None)
   acquire=getattr(backend,'_acquire_mtu',None)
   if callable(acquire):
    # Bleak's documented BlueZ workaround obtains the real negotiated ATT MTU.
    # Never assume the Mac's packet size is available on another adapter.
    try:
     await asyncio.wait_for(acquire(),10)
     mtu=backend.mtu_size
     if not isinstance(mtu,int) or not 23<=mtu<=517:raise ValueError('Invalid MTU')
     limit=max(limit,mtu-3)
    except Exception as error:
     raise RuntimeError(f'Bluetooth image transfer negotiation failed: {type(error).__name__}: {str(error)[:120]}') from None
  self._transfer_write_size=min(244,limit)
  return self._transfer_write_size
 async def upload_native(self,index,data,progress=None):
  if not 1<=index<=20480 or len(data)!=960000:raise ValueError('Invalid 13.3-inch panel data')
  characteristic=self.client.services.get_characteristic(TX)
  # Linux may initially report the default size before MTU negotiation settles.
  for _ in range(10):
   if characteristic.max_write_without_response_size>20:break
   await asyncio.sleep(0.5)
  chunk_size=await self.transfer_size()
  offset=0;phase='start'
  async def send(phase,metadata):
   self._transfer_ack_timeout=40 if phase==2 else 20
   reply=await self.raw(transfer_packet(phase,metadata))
   if not reply or reply[0]!=1:raise RuntimeError('Frame rejected Bluetooth image block: '+reply[:12].hex())
  try:
   await send(0,index.to_bytes(4,'big')+len(data).to_bytes(4,'big'))
   phase='data'
   for offset in range(0,len(data),8192):
    if offset%(8192*8)==0 and progress:progress(offset,len(data),chunk_size)
    block=data[offset:offset+8192]
    metadata=offset.to_bytes(4,'big')+len(block).to_bytes(4,'big')+block
    for attempt in range(3):
     try:
      await send(1,metadata);break
     except (asyncio.TimeoutError,RuntimeError):
      if attempt==2:raise
      await asyncio.sleep(0.1)
   offset=len(data);phase='finish'
   await send(2,b'\0'*4+len(data).to_bytes(4,'big')+crc16(data).to_bytes(2,'big'))
   self._transfer_ack_timeout=20
  except Exception as error:
   raise RuntimeError(f'Bluetooth image transfer {phase} failed at {offset}/{len(data)} bytes; packet size {chunk_size}; {type(error).__name__}: {str(error)[:120]}') from None
 async def command(self,hexdata):
  async with self.lock:
   cipher=Cipher(algorithms.AES(self.key),modes.GCM(self.iv) if self.mode else modes.CTR(self.iv))
   enc=cipher.encryptor();data=enc.update(bytes.fromhex(hexdata))+enc.finalize()
   head=enc.tag[:2] if self.mode else self.iv[:2]
   r=await self.raw(b'\x57'+self.key_id+head+data)
   if len(r)<4 or r[0]!=1:raise RuntimeError('Bluetooth command rejected')
   if self.mode:
    dec=Cipher(algorithms.AES(self.key),modes.GCM(self.iv,b'\0'*16)).decryptor();plain=r[:1]+dec.update(r[4:]);self.iv=(int.from_bytes(self.iv,'big')+1).to_bytes(12,'big')
   else:
    dec=cipher.decryptor();plain=r[:1]+dec.update(r[4:])+dec.finalize()
   return plain
 async def mode_info(self):return (await self.command('0f7b02')).hex()
 async def info(self):return (await self.command('02')).hex()
 async def show(self,index):
  ix=index.to_bytes(2,'little').hex()
  await self.command('0f7a0300'+ix+'00000000')
  return (await self.command('0f7a02'+ix)).hex()
 async def indices(self):
  first=await self.command('0f7b0700')
  if len(first)<3 or not 1<=first[1]<=255 or first[2]!=0:raise RuntimeError('Invalid local image catalogue')
  data=bytearray(first[3:])
  for packet in range(1,first[1]):
   r=await self.command('0f7b07'+bytes([packet]).hex())
   if len(r)<3 or r[1]!=first[1] or r[2]!=packet:raise RuntimeError('Incomplete local image catalogue')
   data.extend(r[3:])
  return [i*8+b+1 for i,v in enumerate(data) for b in range(8) if v&(1<<b)]
 async def normal(self,indices,interval=30):
  if not indices or len(indices)>200:raise ValueError('Normal artwork playlist required')
  prefix='0f7a0301'
  header=prefix+'0000'+len(indices).to_bytes(2,'little').hex()+interval.to_bytes(2,'big').hex()+'000005a07f'
  await self.command(header)
  for offset in range(0,len(indices),5):
   packet=prefix+(offset//5+1).to_bytes(2,'big').hex()+b''.join(i.to_bytes(2,'little') for i in indices[offset:offset+5]).hex()
   await self.command(packet)
