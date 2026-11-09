import unittest,types
from unittest.mock import AsyncMock
from test_controller import manager
class Frame:
 def __init__(self,indices,mode):self.indices=AsyncMock(return_value=indices);self.show=AsyncMock();self.normal=AsyncMock();self.mode_info=AsyncMock(return_value=mode)
 async def __aenter__(self):return self
 async def __aexit__(self,*args):pass
class Tests(unittest.IsolatedAsyncioTestCase):
 def setup_manager(self,on,indices,mode):
  m=manager(on);m.local_key={'key':'private'};m.data['baby_indices']=[8]
  f=Frame(indices,mode);m.local_connection=AsyncMock(return_value=f);m.upload_image=AsyncMock();m.read_image=AsyncMock();return m,f
 async def test_repeat_on_uses_only_bluetooth(self):
  m,f=self.setup_manager(True,[7,8],'0100080000000000')
  await m.reconcile();await m.reconcile()
  self.assertEqual(f.show.await_count,2);m.client.catalogue.assert_not_awaited();m.client.show.assert_not_awaited();m.upload_image.assert_not_awaited()
 async def test_off_retains_one_copy_and_excludes_it(self):
  m,f=self.setup_manager(False,[7,8,9],'0101001e000005a07f02')
  await m.reconcile();f.normal.assert_awaited_once_with([7,9]);m.client.remove.assert_not_awaited();m.client.catalogue.assert_not_awaited();self.assertEqual(m.data['baby_indices'],[8])
 async def test_missing_baby_never_uploads_again(self):
  m,f=self.setup_manager(True,[7],'01000700');await m.reconcile()
  m.upload_image.assert_not_awaited();self.assertEqual(m.status,'error');f.show.assert_not_awaited()
 async def test_bluetooth_failure_never_falls_back_to_cloud(self):
  m,f=self.setup_manager(True,[7,8],'01000800');m.local_connection.side_effect=RuntimeError('offline')
  await m.reconcile();m.client.catalogue.assert_not_awaited();m.client.show.assert_not_awaited();self.assertEqual(m.status,'error')
 async def test_no_normal_art_fails_closed(self):
  m,f=self.setup_manager(False,[8],'010100');await m.reconcile();f.normal.assert_not_awaited();self.assertEqual(m.status,'error')
if __name__=='__main__':unittest.main()
