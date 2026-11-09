"""Original AI Art Frame's verified one-byte local control protocol.

Stored-image control only: firmware 1.0 and 1.4 explicitly reject the Frame 2 bulk
upload command. Do not silently send a photograph through the cloud instead.
"""
from .local_ble import LocalFrame

class OriginalFrame(LocalFrame):
    @staticmethod
    def image_id(index):
        if isinstance(index,bool) or not isinstance(index,int) or not 1<=index<=255:
            raise ValueError('Original-frame image id must be between 1 and 255')
        return bytes([index]).hex()

    async def indices(self):
        info=bytes.fromhex(await self.info())
        if len(info)<7 or info[0]!=1 or info[6]>10 or len(info)<7+info[6]:
            raise RuntimeError('Invalid original-frame image catalogue')
        indices=list(info[7:7+info[6]])
        if any(not i for i in indices) or len(set(indices))!=len(indices):
            raise RuntimeError('Invalid original-frame image ids')
        return indices

    async def show(self,index):
        ix=self.image_id(index)
        if index not in await self.indices():raise ValueError('Picture is not stored on this frame')
        await self.command('0f7a0300'+ix+'00000000')
        return (await self.command('0f7a02'+ix)).hex()

    async def normal(self,indices,interval=30):
        if not indices or len(indices)>10 or len(set(indices))!=len(indices):
            raise ValueError('Original frame needs a playlist of 1 to 10 unique image ids')
        if isinstance(interval,bool) or not isinstance(interval,int) or not 1<=interval<=1440:
            raise ValueError('Slideshow interval must be between 1 and 1440 minutes')
        payload=''.join(self.image_id(i) for i in indices)
        present=set(await self.indices())
        if not set(indices).issubset(present):raise ValueError('Playlist includes a picture not stored on this frame')
        await self.command('0f7a0301'+interval.to_bytes(2,'big').hex()+payload)

    async def upload_native(self,index,data,progress=None):
        raise RuntimeError('Local image upload is not established for this original-frame firmware; no cloud fallback was used')
