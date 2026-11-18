"""Synthetic offline tests: real staged library/gallery code, no HA or network."""
import ast
import asyncio
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from PIL import Image,ImageOps,UnidentifiedImageError

ROOT=Path(__file__).resolve().parents[1]
COMPONENTS=ROOT/'custom_components'
class FrameError(Exception):pass
package=types.ModuleType('pilot');package.__path__=[];sys.modules['pilot']=package
protocol=types.ModuleType('pilot.protocol');protocol.FrameError=FrameError;sys.modules['pilot.protocol']=protocol
spec=importlib.util.spec_from_file_location('pilot.library',str(COMPONENTS/'switchbot_frame_control/library.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);Library=module.Library

# Load the actual Gallery class/helpers without pretending a full HA runtime.
tree=ast.parse((COMPONENTS/'switchbot_frame_control/gallery.py').read_text())
namespace={}
exec('import asyncio,base64,hashlib,io,json,re,os\nfrom pathlib import Path\nfrom datetime import datetime,timezone\nfrom PIL import Image,ImageOps',namespace)
selected=[node for node in tree.body if isinstance(node,(ast.FunctionDef,ast.ClassDef))
          and node.name in ('prepare_transport','Gallery')]
exec(compile(ast.Module(body=selected,type_ignores=[]),'staged_gallery','exec'),namespace)
Gallery=namespace['Gallery']

# Exercise the real normal-send controller entry as well as Library itself.
controller_tree=ast.parse((COMPONENTS/'switchbot_frame_control/__init__.py').read_text())
controller_namespace={'Library':Library,'FrameError':FrameError,'hashlib':hashlib,
                      'io':io,'Image':Image,'ImageOps':ImageOps,'MAX_FILE':8*1024*1024,
                      'UnidentifiedImageError':UnidentifiedImageError}
upload_node=next(n for n in controller_tree.body if isinstance(n,ast.ClassDef) and n.name=='Manager')
upload_node=next(n for n in upload_node.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='upload')
jpeg_node=next(n for n in controller_tree.body if isinstance(n,ast.FunctionDef) and n.name=='jpeg_bytes')
exec(compile(ast.Module(body=[jpeg_node,upload_node],type_ignores=[]),'staged_controller', 'exec'),controller_namespace)

def jpeg(colour=(22,80,130)):
    image=Image.new('RGB',(6,4),colour);buf=io.BytesIO();image.save(buf,'JPEG');return buf.getvalue()

def row(index,status=1):
    return {'imageIndex':index,'status':status,'createdAt':index*100,'id':'synthetic_'+str(index),
            'imageUniqueId':'synthetic_'+str(index),'mainImageUrl':'https://synthetic.invalid/'+str(index)+'.jpg','angle':90}

async def no_sleep(*_):pass

class Client:
    device='synthetic_device';group='synthetic_group'
    def __init__(self,m):
        self.m=m;self.items={i:row(i) for i in (20,31,32)};self.stored=set(self.items);self.selected=20
        self.events=[];self.fail_delivery=False;self.registration_error=False;self.release_timeout=False;self.delete_timeout=False;self.defer_release=False
    async def catalogue(self):return copy.deepcopy(list(self.items.values()))
    async def reported_state(self):return {'9601':{'value':self.selected},'9603':{'value':0},'9606':{'value':sorted(self.stored)+[0]}}
    async def download(self,index,model):self.events.append(('download',index))
    async def select_downloaded(self,index,model):
        if not self.fail_delivery:self.stored.add(index);self.selected=index
        self.events.append(('selection',index));return not self.fail_delivery
    async def show(self,index,model):self.events.append(('show',index));self.selected=index
    async def invoke(self,fn,params=None):
        if fn==9609:self.events.append(('wake',None));return
        if params['1'] in (41,42,43):assert self.m.data['library_device_cleanup']['requests'][str(params['1'])]>0
        else:
            assert any(t['stage']=='device_release' and t['previous']['index']==params['1']
                       for t in self.m.data['library_cleanup_queue'])
            assert any(t['release_requests']>0 for t in self.m.saved[-1]['library_cleanup_queue'])
        self.events.append(('release',params['1']))
        if not self.defer_release:self.stored.discard(params['1'])
        if self.release_timeout:self.release_timeout=False;raise TimeoutError('lost device reply')
    async def post(self,endpoint,data):
        index=(data.get('imageIndexList') or data.get('imageIndexes'))[0]
        assert data['deleteAll'] is False
        if 'syncDeletedImages' in endpoint:
            self.events.append(('sync',index))
            if self.defer_release and index not in self.items:self.stored.discard(index)
        else:
            self.events.append(('delete',index));self.items.pop(index,None)
            if self.delete_timeout:self.delete_timeout=False;raise TimeoutError('lost cloud reply')

class Manager:
    def __init__(self,directory):
        self.frame_id='library_frame';self.config={'model':'frame1','panel_size':'31.5','library_mode':True}
        self.data={'layout':{'orientation':'portrait','flipped':True},'normal_indices':[],
                   'baby_indices':[],'library_mode':True,'library_retained_indices':[31,32]}
        self.lock=asyncio.Lock();self.tasks=set();self.saved=[];self.error=None;self.last_action=''
        self.fail_save=False;self.notifications=False;self.reads=[]
        async def executor(fn,*args):return fn(*args)
        self.hass=types.SimpleNamespace(data={},config=types.SimpleNamespace(config_dir=directory,path=lambda *parts:str(Path(directory).joinpath(*parts))),
                    async_add_executor_job=executor,async_create_task=asyncio.create_task,
                    async_create_background_task=lambda coro,name:asyncio.create_task(coro,name=name))
        self.hass.data['frame_art_gallery']=Gallery(self.hass,{'directory':'gallery'})
        self.client=Client(self)
    def connection_mode(self):return 'wifi'
    def protected_indices(self):return set(self.data['baby_indices'])|{31}
    def desired(self):return self.notifications
    async def save_verified(self):
        if self.fail_save:raise OSError('synthetic persistence failure')
        self.saved.append(copy.deepcopy(self.data))
    async def read_image(self,url):self.reads.append(url);return jpeg()
    async def cloud_art(self,content):
        if self.client.registration_error:raise FrameError('synthetic registration failure')
        digest=hashlib.sha256(content).hexdigest();ledger=self.data.setdefault('cloud_art_uploads',{})
        if digest in ledger:return ledger[digest]
        index=next(i for i in range(21,256) if i not in self.client.items and i not in self.client.stored)
        self.client.events.append(('register',index));self.client.items[index]=row(index);ledger[digest]=index
        return index
    def publish(self,*args,**kwargs):pass

class Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.m=Manager(self.temp.name);self.lib=Library(self.m)
        self.sleep_patch=patch.object(module.asyncio,'sleep',no_sleep);self.sleep_patch.start()
    async def asyncTearDown(self):
        task=getattr(self.m,'library_cleanup_task',None)
        if task is not None:await task
        self.sleep_patch.stop();self.temp.cleanup()
    async def confirmed(self):
        with patch.object(self.lib,'queue_cleanup'):
            return await self.lib.deliver(jpeg((12,34,56)))
    async def clean(self):
        for _ in range(40):
            result=await self.lib.cleanup()
            if not self.lib.cleanup_pending():return result
        raise FrameError('Cleanup remains pending')
    def mutations(self):return [e for e in self.m.client.events if e[0] in ('release','delete','sync')]
    async def test_new_stored_and_selected_returns_before_old_archive_or_delete(self):
        async with self.m.lock:
            result=await self.lib.deliver(jpeg((12,34,56)))
            self.assertTrue(result['local_storage_verified']);self.assertTrue(result['cleanup_pending'])
            self.assertEqual(self.m.reads,[]);self.assertEqual(self.m.client.selected,21);self.assertIn(21,self.m.client.stored)
            self.assertEqual(self.mutations(),[])
        await self.m.library_cleanup_task
        self.assertEqual(self.mutations(),[('release',20),('delete',20),('sync',20)])
        self.assertTrue(self.m.reads);self.assertEqual(self.m.data['library_transaction']['stage'],'complete')
    async def test_registration_failure_never_archives_or_deletes_previous(self):
        self.m.client.registration_error=True
        with self.assertRaises(FrameError):await self.lib.deliver(jpeg())
        self.assertEqual(self.m.reads,[]);self.assertEqual(self.mutations(),[])
    async def test_unconfirmed_delivery_never_cleans_up(self):
        self.m.client.fail_delivery=True;result=await self.lib.deliver(jpeg())
        self.assertFalse(result['local_storage_verified']);self.assertEqual(self.mutations(),[])
        self.assertEqual(self.m.data['library_transaction']['stage'],'awaiting_delivery')
    async def test_capacity_full_never_predeletes(self):
        self.m.client.items={i:row(i) for i in range(10,20)};self.m.client.stored=set(self.m.client.items);self.m.client.selected=10
        with self.assertRaisesRegex(FrameError,'never pre-deletes'):await self.lib.deliver(jpeg())
        self.assertEqual(self.m.client.events,[])
    async def test_cleanup_pending_allows_another_upload_without_losing_intent(self):
        await self.confirmed()
        first=copy.deepcopy(self.m.data['library_cleanup_queue'][0])
        with patch.object(self.lib,'queue_cleanup'):await self.lib.deliver(jpeg((0,0,0)))
        self.assertEqual(sum(e[0]=='register' for e in self.m.client.events),2)
        self.assertEqual(self.m.data['library_cleanup_queue'][0],first)
        self.assertEqual(len(self.m.data['library_cleanup_queue']),2)
        self.assertEqual(self.mutations(),[])
    async def test_selected_notification_remains(self):
        self.m.client.selected=31;await self.confirmed();await self.clean()
        self.assertEqual(self.mutations(),[]);self.assertIn(31,self.m.client.items)
    async def test_explicit_restore_32_remains(self):
        self.m.client.selected=32;await self.confirmed();await self.clean()
        self.assertEqual(self.mutations(),[]);self.assertIn(32,self.m.client.items)
    async def test_existing_normal_restore_set_remains(self):
        self.m.data['normal_indices']=[20];await self.confirmed();await self.clean();self.assertEqual(self.mutations(),[])
    async def test_bin_snapshot_blocks_upload(self):
        self.m.hass.data['frame_bin_reminder']=types.SimpleNamespace(manager=self.m,data={'snapshot':{'index':32},'slot':{'index':31}})
        with self.assertRaisesRegex(FrameError,'Notification'):await self.lib.deliver(jpeg())
        self.assertEqual(self.m.client.events,[])
    async def test_notification_appearing_after_success_blocks_cleanup(self):
        await self.confirmed();self.m.notifications=True
        with self.assertRaises(FrameError):await self.lib.cleanup()
        self.assertEqual(self.mutations(),[])
    async def test_current_selection_is_never_deleted(self):
        await self.confirmed();self.m.client.selected=20
        with self.assertRaises(FrameError):await self.lib.cleanup()
        self.assertEqual(self.mutations(),[])
    async def test_reused_previous_slot_is_never_deleted(self):
        await self.confirmed();self.m.client.items[20]['id']='reused'
        with self.assertRaisesRegex(FrameError,'reused'):await self.lib.cleanup()
        self.assertEqual(self.mutations(),[])
    async def test_unrelated_membership_change_does_not_stall_identity_bound_cleanup(self):
        await self.confirmed();self.m.client.items.pop(32)
        await self.clean()
        self.assertNotIn(20,self.m.client.items);self.assertIn(31,self.m.client.items)
    async def test_backup_corruption_stops_cleanup(self):
        await self.confirmed();transaction=self.m.data['library_transaction'];gallery=self.m.hass.data['frame_art_gallery']
        gallery.path(transaction['new_gallery_id']).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'checksum'):await self.lib.cleanup()
        self.assertEqual(self.mutations(),[])
    async def test_persistence_failure_prevents_first_mutation(self):
        self.m.fail_save=True
        with self.assertRaises(OSError):await self.lib.deliver(jpeg())
        self.assertEqual(self.m.client.events,[])
    async def test_lost_device_reply_resumes_without_second_release(self):
        await self.confirmed();self.m.client.release_timeout=True
        with self.assertRaises(TimeoutError):await self.clean()
        await self.clean();self.assertEqual(sum(e[0]=='release' for e in self.m.client.events),1)
    async def test_lost_cloud_reply_does_not_repeat_delete(self):
        await self.confirmed();self.m.client.delete_timeout=True
        with self.assertRaises(TimeoutError):await self.clean()
        await self.clean();self.assertEqual(sum(e[0]=='delete' for e in self.m.client.events),1)
    async def test_cleanup_is_idempotent(self):
        await self.confirmed();await self.clean();before=list(self.m.client.events);await self.clean()
        self.assertEqual(before,self.m.client.events)
    async def test_durable_cleanup_can_resume_after_restart(self):
        await self.confirmed();saved=copy.deepcopy(self.m.saved[-1]);other=Manager(self.temp.name);other.data=saved;other.client=self.m.client;other.client.m=other
        for _ in range(5):await Library(other).cleanup()
        self.assertFalse(Library(other).cleanup_pending())
    async def test_release_budget_persists(self):
        await self.confirmed();self.m.data['library_transaction']['release_requests']=2
        self.m.data['library_cleanup_queue'][0]['release_requests']=2
        self.m.client.defer_release=True
        await self.clean()
        self.assertEqual(self.m.data['library_cleanup_queue'][0]['release_requests'],2)
        self.assertEqual(self.mutations(),[('delete',20),('sync',20)])
        self.assertEqual(self.m.data['library_transaction']['stage'],'complete')
    async def test_frame1_eviction_reports_absence_only_after_cloud_delete_and_sync(self):
        await self.confirmed();self.m.client.defer_release=True
        await self.clean()
        self.assertEqual(self.mutations(),[('release',20),('delete',20),('sync',20)])
        self.assertNotIn(20,self.m.client.stored);self.assertNotIn(20,self.m.client.items)
        self.assertEqual(self.m.data['library_transaction']['stage'],'complete')
    async def test_background_failure_does_not_change_success_into_send_failure(self):
        async with self.m.lock:
            result=await self.lib.deliver(jpeg());self.m.notifications=True
        await self.m.library_cleanup_task
        self.assertTrue(result['local_storage_verified']);self.assertIn('library_cleanup_error',self.m.data)
        self.assertEqual(self.mutations(),[])
    async def test_zero_status_blocks_new_send(self):
        self.m.client.items[20]['status']=0
        with self.assertRaisesRegex(FrameError,'unsettled'):await self.lib.deliver(jpeg())
        self.assertEqual(self.m.client.events,[])
    async def test_adopt_44_has_no_registration_or_selection(self):
        self.m.client.items[44]=row(44,0);self.m.client.stored.add(44)
        result=await self.lib.set_enabled(True,[32],44)
        self.assertTrue(result['enabled']);self.assertEqual(self.m.data['library_transaction']['new_index'],44)
        self.assertEqual(self.m.client.events,[]);self.assertIn(32,self.lib.protected())
        with self.assertRaises(FrameError):await self.lib.deliver(jpeg((0,0,0)))
    async def test_activation_reconciles_stored_selected_and_retained_legacy_status_zero(self):
        self.m.client.items[20]['status']=0;self.m.client.items[32]['status']=0
        self.m.client.items[44]=row(44,0);self.m.client.stored.add(44)
        await self.lib.set_enabled(True,[31,32],44)
        self.assertEqual(self.lib.unsettled(self.m.client.items),[44]);self.assertEqual(self.m.client.events,[])
    async def test_recover_44_selects_existing_without_registration(self):
        self.m.client.items[44]=row(44,0);self.m.client.stored.add(44)
        await self.lib.set_enabled(True,[32],44)
        async with self.m.lock:result=await self.lib.resume_delivery()
        await self.m.library_cleanup_task
        self.assertTrue(result['local_storage_verified']);self.assertEqual(self.m.client.events,[('show',44)])
        self.assertEqual(self.lib.unsettled(self.m.client.items),[])
    async def test_stored_only_migration_images_do_not_block_backup_when_verified(self):
        self.m.client.stored.update({41,42,43})
        image_id=await self.lib.archive(20,row(20));gallery=self.m.hass.data['frame_art_gallery']
        with patch.object(gallery,'migration_backup',return_value=image_id):result=await self.lib.backup_all()
        self.assertTrue(result['complete']);self.assertTrue(result['backups']['41']['stored_only'])
        self.assertEqual(self.m.client.events,[])
    async def test_unbacked_stored_only_slot_stops_activation(self):
        self.m.client.stored.add(41)
        with self.assertRaises(FileNotFoundError):await self.lib.set_enabled(True,[32])
        self.assertEqual(self.m.client.events,[])
    async def test_lost_bind_receipt_fails_closed_without_duplicate(self):
        raw=jpeg();await self.lib.begin(raw)
        self.m.data['cloud_art_uploads']={hashlib.sha256(raw).hexdigest():21}
        with self.assertRaisesRegex(FrameError,'receipt'):await self.lib.deliver(raw)
        self.assertEqual(self.m.client.events,[])
    async def test_untested_size_is_not_supported(self):
        self.m.config['panel_size']='13.3'
        with self.assertRaises(FrameError):await self.lib.snapshot()
    async def test_per_frame_opt_in_required(self):
        self.m.data.pop('library_mode')
        with self.assertRaisesRegex(FrameError,'Opt into'):await self.lib.deliver(jpeg())
    async def test_archive_all_is_local_only_and_byte_exact(self):
        result=await self.lib.backup_all();self.assertTrue(result['complete']);self.assertEqual(len(result['backups']),3)
        self.assertEqual(self.m.client.events,[])
        for entry in result['backups'].values():self.assertEqual(await self.lib.verify(entry['gallery_id']),jpeg())
    async def test_gallery_reimport_does_not_duplicate_or_overwrite_existing(self):
        gallery=self.m.hass.data['frame_art_gallery'];gallery.root.mkdir();(gallery.root/'index.json').write_text('{"keep":{"name":"unchanged"}}')
        one=await self.lib.archive(20,row(20));two=await self.lib.archive(20,row(20))
        self.assertEqual(one,two);index=gallery.read_index();self.assertEqual(len(index),2);self.assertEqual(index['keep'],{'name':'unchanged'})
        self.assertEqual(len(index[one]['origins']),1)
    async def test_transport_gallery_send_skips_second_layout_transform(self):
        image_id=await self.lib.archive(20,row(20));gallery=self.m.hass.data['frame_art_gallery'];calls=[]
        async def upload(raw,**kwargs):calls.append(raw);return {'accepted':True}
        self.m.upload=upload;self.m.hass.data['switchbot_frame_control']=types.SimpleNamespace(select=lambda _:self.m)
        await gallery.send(image_id,'library_frame');self.assertEqual(calls,[jpeg()])

    async def test_legacy_awaiting_absence_is_reconciled_without_remote_mutation(self):
        await self.confirmed()
        legacy=self.m.data.pop('library_cleanup_queue')[0]
        old_id=await self.lib.archive(20,row(20))
        legacy['previous']['gallery_id']=old_id
        legacy.update(stage='awaiting_absence',release_requests=2,delete_requests=2,sync_requests=2)
        self.m.data['library_transaction']=copy.deepcopy(legacy)
        self.m.client.items.pop(20);self.m.client.stored.discard(20)
        await self.lib.cleanup()
        self.assertFalse(self.lib.cleanup_pending());self.assertEqual(self.mutations(),[])
        self.assertEqual(self.m.data['library_cleanup_queue'][0]['previous'],legacy['previous'])

    async def test_legacy_migration_is_durable_before_new_registration(self):
        await self.confirmed()
        legacy=self.m.data.pop('library_cleanup_queue')[0]
        legacy['stage']='awaiting_absence';legacy['delete_requests']=2
        self.m.data['library_transaction']=copy.deepcopy(legacy)
        with patch.object(self.lib,'queue_cleanup'):await self.lib.deliver(jpeg((2,4,6)))
        self.assertEqual(self.m.data['library_cleanup_queue'][0],legacy)
        self.assertEqual(self.m.saved[-1]['library_cleanup_queue'][0],legacy)
        self.assertEqual(len(self.m.data['library_cleanup_queue']),2)

    async def test_failed_migration_save_restores_original_intent(self):
        await self.confirmed()
        legacy=self.m.data.pop('library_cleanup_queue')[0]
        self.m.data['library_transaction']=legacy
        before=copy.deepcopy(self.m.data);events=list(self.m.client.events)
        self.m.fail_save=True
        with self.assertRaises(OSError):await self.lib.deliver(jpeg((4,5,6)))
        self.assertEqual(self.m.data,before);self.assertEqual(self.m.client.events,events)

    async def test_multi_delivery_queue_survives_restart_and_drains_exact_targets(self):
        await self.confirmed()
        with patch.object(self.lib,'queue_cleanup'):await self.lib.deliver(jpeg((4,5,6)))
        queue=copy.deepcopy(self.m.data['library_cleanup_queue'])
        other=Manager(self.temp.name);other.data=copy.deepcopy(self.m.saved[-1])
        other.client=self.m.client;other.client.m=other
        for _ in range(5):await Library(other).cleanup()
        self.assertFalse(Library(other).cleanup_pending())
        self.assertEqual([t['previous']['identity'] for t in other.data['library_cleanup_queue']],
                         [t['previous']['identity'] for t in queue])
        self.assertEqual(other.client.selected,22);self.assertEqual(set(other.client.items),{22,31,32})

    async def test_reused_old_target_does_not_block_new_send_or_other_cleanup(self):
        await self.confirmed();self.m.client.items[20]['id']='reused'
        with patch.object(self.lib,'queue_cleanup'):await self.lib.deliver(jpeg((4,5,6)))
        for _ in range(5):
            with self.assertRaises(FrameError):await self.lib.cleanup()
        queue=self.m.data['library_cleanup_queue']
        self.assertNotEqual(queue[0]['stage'],'complete');self.assertEqual(queue[1]['stage'],'complete')
        self.assertIn(20,self.m.client.items);self.assertNotIn(21,self.m.client.items)
        self.assertNotIn(('delete',20),self.mutations())

    async def test_protection_added_after_delivery_preserves_intent_and_image(self):
        await self.confirmed();self.m.data['normal_indices']=[20]
        with self.assertRaisesRegex(FrameError,'reference'):await self.lib.cleanup()
        self.assertTrue(self.lib.cleanup_pending());self.assertIn(20,self.m.client.items)
        self.assertEqual(self.mutations(),[])

    async def test_queue_is_not_overwritten_by_failed_second_delivery(self):
        await self.confirmed();before=copy.deepcopy(self.m.data['library_cleanup_queue'])
        self.m.client.fail_delivery=True
        result=await self.lib.deliver(jpeg((4,5,6)))
        self.assertFalse(result['local_storage_verified'])
        self.assertEqual(self.m.data['library_cleanup_queue'],before);self.assertEqual(self.mutations(),[])

    async def test_exhausted_cleanup_budget_does_not_reserve_capacity(self):
        await self.confirmed();t=self.m.data['library_cleanup_queue'][0]
        t.update(wake_requests=2,release_requests=2,delete_requests=2,sync_requests=2)
        with self.assertRaisesRegex(FrameError,'budget'):await self.lib.cleanup()
        with patch.object(self.lib,'queue_cleanup'):result=await self.lib.deliver(jpeg((4,5,6)))
        self.assertTrue(result['local_storage_verified']);self.assertEqual(self.mutations(),[])
        self.assertEqual(self.m.data['library_cleanup_queue'][0]['delete_requests'],2)

    async def test_full_device_with_spare_cloud_capacity_still_refuses_predelete(self):
        self.m.client.stored=set(range(20,30))
        with self.assertRaisesRegex(FrameError,'never pre-deletes'):await self.lib.deliver(jpeg())
        self.assertEqual(self.m.client.events,[])

    async def test_same_saved_source_reuses_slot_without_duplicate_or_new_intent(self):
        await self.confirmed();await self.clean()
        with patch.object(self.lib,'queue_cleanup'):result=await self.lib.deliver(jpeg((12,34,56)))
        self.assertTrue(result['local_storage_verified'])
        self.assertEqual(sum(e[0]=='register' for e in self.m.client.events),1)
        self.assertEqual(len(self.m.data['library_cleanup_queue']),1)
        self.assertFalse(self.lib.cleanup_pending())

    async def test_pending_poll_releases_lock_and_only_one_worker_exists(self):
        await self.confirmed()
        polling=asyncio.Event();resume=asyncio.Event()
        async def pause(*_):polling.set();await resume.wait()
        with patch.object(module.asyncio,'sleep',pause):
            self.lib.queue_cleanup();task=self.m.library_cleanup_task
            await asyncio.wait_for(polling.wait(),1)
            self.lib.queue_cleanup();self.assertIs(self.m.library_cleanup_task,task)
            async with self.m.lock:
                result=await self.lib.deliver(jpeg((4,5,6)))
                self.assertTrue(result['local_storage_verified'])
                self.assertEqual(len(self.m.data['library_cleanup_queue']),2)
            resume.set();await asyncio.wait_for(task,2)
        self.assertFalse(self.lib.cleanup_pending());self.assertEqual(self.m.client.selected,22)

    async def test_cancellation_preserves_pending_intent_for_restart(self):
        await self.confirmed();polling=asyncio.Event();resume=asyncio.Event()
        async def pause(*_):polling.set();await resume.wait()
        with patch.object(module.asyncio,'sleep',pause):
            self.lib.queue_cleanup();task=self.m.library_cleanup_task
            await asyncio.wait_for(polling.wait(),1);task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        self.m.library_cleanup_task=None
        self.assertTrue(self.lib.cleanup_pending())
        other=Manager(self.temp.name);other.data=copy.deepcopy(self.m.saved[-1]);other.client=self.m.client;other.client.m=other
        for _ in range(5):await Library(other).cleanup()
        self.assertFalse(Library(other).cleanup_pending())

    async def test_diagnostics_never_include_cloud_identity_or_url(self):
        await self.confirmed();result=await self.lib.inspect()
        text=json.dumps(result['cleanup_queue'])+json.dumps(result['transaction'])
        self.assertNotIn('synthetic.invalid',text);self.assertNotIn('synthetic_',text)
        self.assertEqual(result['spare_capacity'],6)
        self.assertEqual(result['cleanup_queue'][0]['previous_index'],20)

    async def test_corrupt_previous_backup_prevents_any_remote_cleanup(self):
        await self.confirmed();await self.lib.cleanup()
        transaction=self.m.data['library_cleanup_queue'][0]
        self.m.hass.data['frame_art_gallery'].path(transaction['previous']['gallery_id']).write_bytes(b'corrupt')
        events=list(self.m.client.events)
        with self.assertRaisesRegex(ValueError,'checksum'):await self.lib.cleanup()
        self.assertEqual(self.m.client.events,events);self.assertTrue(self.lib.cleanup_pending())

    async def test_failed_queue_save_prevents_remote_cleanup(self):
        await self.confirmed();self.m.fail_save=True;events=list(self.m.client.events)
        with self.assertRaises(OSError):await self.lib.cleanup()
        self.assertEqual(self.m.client.events,events);self.assertTrue(self.lib.cleanup_pending())

    async def test_cleanup_preserves_every_gallery_original(self):
        await self.confirmed();await self.lib.cleanup()
        gallery=self.m.hass.data['frame_art_gallery']
        before={p.name:p.read_bytes() for p in gallery.root.iterdir() if p.suffix=='.jpg'}
        await self.clean()
        for name,raw in before.items():self.assertEqual((gallery.root/name).read_bytes(),raw)
        self.assertEqual(len([p for p in gallery.root.iterdir() if p.suffix=='.jpg']),len(before))

    async def test_real_gallery_and_controller_entry_accepts_spare_capacity_with_old_cleanup(self):
        await self.confirmed();old=copy.deepcopy(self.m.data['library_cleanup_queue'][0])
        self.m.upload=types.MethodType(controller_namespace['upload'],self.m)
        async def report(error):raise AssertionError('unexpected send failure') from error
        self.m.report_failure=report
        self.m.hass.data['switchbot_frame_control']=types.SimpleNamespace(select=lambda _:self.m)
        image_id=await self.lib.archive(0,{},raw=jpeg((3,6,9)),known_layout=True)
        with patch.object(Library,'queue_cleanup'):
            result=await self.m.hass.data['frame_art_gallery'].send(image_id,'library_frame')
        self.assertTrue(result['local_storage_verified']);self.assertEqual(self.m.client.selected,22)
        self.assertEqual(self.m.data['library_cleanup_queue'][0],old)
        self.assertEqual(self.mutations(),[])

    async def test_real_controller_entry_still_guards_active_notification(self):
        self.m.upload=types.MethodType(controller_namespace['upload'],self.m)
        self.m.notifications=True
        with self.assertRaisesRegex(FrameError,'baby picture is active'):await self.m.upload(jpeg())
        self.assertEqual(self.m.client.events,[])

if __name__=='__main__':unittest.main()

class PublicScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_second_frame_is_supported_without_household_name_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            manager=Manager(directory);manager.frame_id='another_frame'
            selected,stored,items=await Library(manager).snapshot()
            self.assertEqual(selected,20);self.assertEqual(stored,set(items))

    async def test_disabling_with_queued_cleanup_cannot_abandon_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            manager=Manager(directory);library=Library(manager)
            with patch.object(library,'queue_cleanup'):await library.deliver(jpeg())
            with self.assertRaisesRegex(FrameError,'Resolve'):
                await library.set_enabled(False,[])
            self.assertTrue(library.enabled());self.assertTrue(library.cleanup_pending())

    async def test_other_generation_and_mode_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            manager=Manager(directory);library=Library(manager)
            manager.config['model']='frame2'
            with self.assertRaises(FrameError):await library.inspect()
            manager.config['model']='frame1';manager.connection_mode=lambda:'hybrid'
            with self.assertRaises(FrameError):await library.inspect()
            self.assertEqual(manager.client.events,[])
