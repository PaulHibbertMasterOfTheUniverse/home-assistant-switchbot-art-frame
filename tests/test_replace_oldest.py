import unittest
from unittest.mock import AsyncMock,patch
from test_controller import manager,FrameError
from test_fully_local import picture

class Tests(unittest.IsolatedAsyncioTestCase):
 def setup_frame(self):
  m=manager();m.config['model']='frame1';m.data['connection_mode']='wifi'
  m.client.reported_state=AsyncMock(return_value={'9606':{'value':list(range(1,11))}})
  m.client.catalogue=AsyncMock(return_value=[{'imageIndex':i,'createdAt':str((11-i)*1000)} for i in range(1,11)]+[{'imageIndex':99,'createdAt':'1'}])
  m.client.invoke=AsyncMock();m.client.post=AsyncMock();m.client.device='D';m.client.group='G';m.archive_cloud_art=AsyncMock();return m
 async def test_oldest_is_by_date_and_only_from_stored_pictures(self):
  m=self.setup_frame();m.data['baby_indices']=[10]
  self.assertEqual(await m.oldest_stored(await m.client.reported_state()),{'index':9,'created_at':2000})
 async def test_capacity_offers_replacement_without_deleting_or_uploading(self):
  m=self.setup_frame();m.client.upload_assets=AsyncMock()
  with self.assertRaises(FrameError) as caught:await m.cloud_art(picture())
  self.assertEqual(caught.exception.replacement['index'],10)
  m.client.invoke.assert_not_awaited();m.client.upload_assets.assert_not_awaited()
 async def test_confirmation_is_rechecked_and_wrong_oldest_is_never_removed(self):
  m=self.setup_frame()
  with self.assertRaisesRegex(FrameError,'has changed'):await m.replace_oldest(9)
  m.client.invoke.assert_not_awaited()
 async def test_archives_before_freeing_only_confirmed_device_and_cloud_copy(self):
  m=self.setup_frame();m.data['normal_indices']=list(range(1,11))
  m.client.reported_state.side_effect=[{'9606':{'value':list(range(1,11))}},{'9606':{'value':list(range(1,10))+[0]}}]
  full=m.client.catalogue.return_value;m.client.catalogue.side_effect=[full,full,[i for i in full if i['imageIndex']!=10]]
  await m.replace_oldest(10)
  m.archive_cloud_art.assert_awaited_once_with(10,full)
  self.assertEqual(m.client.post.await_count,2)
  self.assertEqual(m.client.post.await_args_list[0].args[1]['imageIndexList'],[10])
  self.assertFalse(m.client.post.await_args_list[0].args[1]['deleteAll'])
  m.client.invoke.assert_awaited_once_with(9601,{'0':2,'1':10});m.client.remove.assert_not_awaited()
  self.assertNotIn(10,m.data['normal_indices'])
 async def test_if_space_is_already_free_nothing_is_removed(self):
  m=self.setup_frame();m.client.reported_state.return_value={'9606':{'value':[1,2,3]}};m.client.catalogue.return_value=[{'imageIndex':i,'createdAt':'1000'} for i in (1,2,3)]
  await m.replace_oldest(10);m.client.invoke.assert_not_awaited()
 async def test_unknown_creation_date_stops_replacement(self):
  m=self.setup_frame();m.client.catalogue.return_value=[{'imageIndex':i} for i in range(1,11)]
  with self.assertRaisesRegex(FrameError,'Cannot establish'):await m.replace_oldest(10)
  m.client.invoke.assert_not_awaited()
 async def test_pending_registration_and_invalid_image_never_delete(self):
  m=self.setup_frame();m.data['pending_cloud_registration']={'sha256':'uncertain'}
  with self.assertRaisesRegex(FrameError,'pending upload'):await m.replace_oldest(10)
  m.client.invoke.assert_not_awaited()
  with self.assertRaises(FrameError):await m.upload(b'not an image',replace_index=10)
  m.client.invoke.assert_not_awaited()
 async def test_unconfirmed_removal_stops_before_registering(self):
  m=self.setup_frame()
  full=m.client.catalogue.return_value;m.client.catalogue.side_effect=[full,full,[i for i in full if i['imageIndex']!=10]]
  with patch('asyncio.sleep',new=AsyncMock()):
   with self.assertRaisesRegex(FrameError,'not confirmed'):await m.replace_oldest(10)
  self.assertEqual(m.client.invoke.await_count,1)

 async def test_backup_failure_prevents_any_deletion(self):
  m=self.setup_frame();m.archive_cloud_art.side_effect=FrameError('Backup failed')
  with self.assertRaisesRegex(FrameError,'Backup failed'):await m.replace_oldest(10)
  m.client.invoke.assert_not_awaited();m.client.post.assert_not_awaited()
 async def test_cloud_full_still_offers_replacement_with_free_device_slot(self):
  m=self.setup_frame();m.client.reported_state.return_value={'9606':{'value':list(range(1,10))+[0]}}
  with self.assertRaises(FrameError) as caught:await m.cloud_art(picture())
  self.assertEqual(caught.exception.replacement['index'],9);m.client.invoke.assert_not_awaited()
