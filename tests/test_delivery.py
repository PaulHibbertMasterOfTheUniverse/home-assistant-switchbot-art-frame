"""Actual asynchronous worker with synthetic clients, durable receipts and clocks."""
import asyncio
import ast
import base64
import binascii
import copy
import json
import tempfile
import types
import unittest
from unittest.mock import patch

from test_library import Library, Manager, FrameError, jpeg, row, module, controller_namespace, controller_tree


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.m=Manager(self.temp.name);self.lib=Library(self.m)
        self.clock=types.SimpleNamespace(now=1000)
        self.clock.time=lambda:self.clock.now
        self.real_sleep=asyncio.sleep
        async def sleep(seconds):
            self.clock.now+=seconds
            await self.real_sleep(0)
        self.patches=[patch.object(module,'time',self.clock),
                      patch.object(module.asyncio,'sleep',sleep),
                      patch.object(Library,'queue_cleanup')]
        for p in self.patches:p.start()
        self.published=[]
        self.m.publish=lambda *a,**k:self.published.append((a,k))

    async def asyncTearDown(self):
        for task in list(self.m.tasks):
            if not task.done():task.cancel()
            try:await task
            except asyncio.CancelledError:pass
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    async def send(self, raw=None):
        async with self.m.lock:return await self.lib.deliver(raw or jpeg())

    async def finish(self):
        await asyncio.wait_for(self.m.library_delivery_task, 3)
        return self.lib.current_operation()

    async def registered(self):
        with patch.object(self.lib,'queue_delivery'):await self.send()
        async with self.m.lock:await self.lib.delivery_step()
        t=self.m.data['library_transaction']
        self.assertEqual(t['new_index'],21)
        return t

    def commands(self, name):return [e for e in self.m.client.events if e[0]==name]

    async def test_prompt_pending_before_registration_or_device_commands(self):
        response=await self.send()
        self.assertTrue(response['pending']);self.assertFalse(response['local_storage_verified'])
        self.assertEqual(self.m.client.events,[])
        await self.finish()
        self.assertEqual(self.m.client.selected,21)

    async def test_normal_http_entry_returns_before_slow_encoder_and_registration(self):
        """Exercise actual Manager.upload, not just Library.deliver."""
        encoding_started=asyncio.Event();allow_encoding=asyncio.Event()
        registering=asyncio.Event();allow_registration=asyncio.Event()
        prepare=self.m.prepare_library_source;cloud=self.m.cloud_art
        async def slow_prepare(raw):
            encoding_started.set();await allow_encoding.wait();return await prepare(raw)
        async def slow_register(raw):
            registering.set();await allow_registration.wait();return await cloud(raw)
        self.m.prepare_library_source=slow_prepare;self.m.cloud_art=slow_register
        self.m.upload=types.MethodType(controller_namespace['upload'],self.m)
        async def fail(error):raise AssertionError('Unexpected foreground error') from error
        self.m.report_failure=fail
        view_node=next(n for n in controller_tree.body if isinstance(n,ast.ClassDef) and n.name=='UploadView')
        view_namespace={'HomeAssistantView':object,'DOMAIN':'switchbot_frame_control','FrameError':FrameError,
            'MAX_FILE':8*1024*1024,'base64':base64,'binascii':binascii,
            'web':types.SimpleNamespace(json_response=lambda data,**_:data)}
        exec(compile(ast.Module(body=[view_node],type_ignores=[]),'staged_upload_view','exec'),view_namespace)
        view=view_namespace['UploadView'](types.SimpleNamespace(select=lambda _:self.m))
        async def request_json():return {'image':base64.b64encode(jpeg()).decode(),
            'frame_id':'library_frame','layout':self.m.data['layout']}
        request=types.SimpleNamespace(content_length=1000,json=request_json,
            get=lambda key:types.SimpleNamespace(is_admin=True))
        with patch.dict(controller_namespace,{'Library':Library}):
            response=await asyncio.wait_for(view.post(request),0.5)
        self.assertTrue(response['pending']);self.assertFalse(response['local_storage_verified'])
        receipt=self.m.saved[-1]['library_submission']
        self.assertEqual(receipt['stage'],'prepared');self.assertTrue(receipt['source_b64'])
        self.assertEqual(self.m.client.events,[])
        await asyncio.wait_for(encoding_started.wait(),1)
        self.assertFalse(allow_encoding.is_set())
        with patch.dict(controller_namespace,{'Library':Library}):
            retry=await asyncio.wait_for(self.m.upload(jpeg()),0.5)
        self.assertTrue(retry['pending'])
        allow_encoding.set();await asyncio.wait_for(registering.wait(),1)
        self.assertEqual(self.m.saved[-1]['library_transaction']['stage'],'registering')
        self.assertEqual(self.m.saved[-1]['library_transaction']['delivery']['registration_attempts'],1)
        with patch.dict(controller_namespace,{'Library':Library}):
            retry=await asyncio.wait_for(self.m.upload(jpeg()),0.5)
            with self.assertRaisesRegex(FrameError,'active'):
                await asyncio.wait_for(self.m.upload(jpeg((3,4,5))),0.5)
        self.assertTrue(retry['pending'])
        allow_registration.set();await self.finish()

    async def test_raw_submission_survives_restart_before_any_encoding(self):
        with patch.object(self.lib,'queue_delivery'):
            async with self.m.lock:response=await self.lib.submit(jpeg())
        self.assertTrue(response['pending']);saved=copy.deepcopy(self.m.saved[-1])
        other=Manager(self.temp.name);other.data=saved;other.client=self.m.client;other.client.m=other
        self.m=other;self.lib=Library(other);self.lib.queue_delivery()
        t=await self.finish();self.assertEqual(t['stage'],'complete')
        self.assertEqual(len(self.commands('register')),1)

    async def test_failed_source_persistence_returns_no_acceptance_or_command(self):
        self.m.fail_save=True
        with self.assertRaises(OSError):
            async with self.m.lock:await self.lib.submit(jpeg())
        self.assertNotIn('library_submission',self.m.data)
        self.assertEqual(self.m.client.events,[])

    async def test_concurrent_exact_raw_submissions_share_durable_operation(self):
        with patch.object(self.lib,'queue_delivery'):
            async with self.m.lock:
                first=await self.lib.submit(jpeg());second=await self.lib.submit(jpeg())
        self.assertEqual(first['delivery']['operation_id'],second['delivery']['operation_id'])
        self.lib.queue_delivery();await self.finish()
        self.assertEqual(len(self.commands('register')),1)

    async def test_corrupt_saved_source_fails_closed_without_registration(self):
        with patch.object(self.lib,'queue_delivery'):
            async with self.m.lock:await self.lib.submit(jpeg())
        self.m.data['library_submission']['source_b64']='Y29ycnVwdA=='
        self.lib.queue_delivery();await self.finish()
        self.assertEqual(self.lib.current_operation()['stage'],'delivery_error')
        self.assertEqual(self.m.client.events,[])

    async def test_wake_settle_and_fresh_storage_before_selection_with_saved_budgets(self):
        invoke=self.m.client.invoke;show=self.m.client.show;times={}
        async def guarded_invoke(fn,params=None):
            self.assertTrue(self.m.lock.locked())
            d=self.m.saved[-1]['library_transaction']['delivery']
            if fn==9609:
                self.assertEqual(d['download_attempts'],1)
                times['wake']=self.clock.now
            else:
                self.assertEqual(d['phase'],'waiting_storage')
                self.assertGreaterEqual(self.clock.now-times['wake'],5)
            return await invoke(fn,params)
        async def guarded_show(index,model):
            self.assertIn(index,self.m.client.stored)
            self.assertEqual(self.m.saved[-1]['library_transaction']['delivery']['selection_attempts'],1)
            return await show(index,model)
        self.m.client.invoke=guarded_invoke;self.m.client.show=guarded_show
        self.m.client.select_downloaded=lambda *_:self.fail('Duplicate polling helper used')
        await self.send();t=await self.finish()
        self.assertEqual(t['stage'],'complete')
        self.assertEqual([e[0] for e in self.m.client.events],['register','wake','download','show'])

    async def test_exact_source_status_zero_resumes_existing_registration(self):
        await self.registered();self.m.client.items[21]['status']=0
        response=await self.send()
        self.assertTrue(response['pending']);await self.finish()
        self.assertEqual(len(self.commands('register')),1)
        self.assertEqual(self.m.client.selected,21)

    async def test_unrelated_unsettled_image_still_blocks_exact_source(self):
        await self.registered();self.m.client.items[31]['status']=0
        with self.assertRaisesRegex(FrameError,'Unrelated'):await self.send()
        self.assertEqual(self.commands('wake'),[])

    async def test_other_source_cannot_replace_pending_intent(self):
        await self.registered()
        with self.assertRaisesRegex(FrameError,'different library transaction'):
            await self.send(jpeg((1,2,3)))
        self.assertEqual(len(self.commands('register')),1)

    async def test_exhaustion_persisted_and_same_source_cannot_reset_budget(self):
        self.m.client.fail_delivery=True
        await self.send();t=await self.finish()
        self.assertEqual(t['stage'],'delivery_exhausted')
        self.assertEqual(len(self.commands('download')),2)
        self.assertEqual(self.commands('show'),[])
        events=list(self.m.client.events)
        response=await self.send()
        self.assertFalse(response['pending']);self.assertFalse(response['local_storage_verified'])
        self.assertEqual(self.m.client.events,events)
        self.assertEqual(self.m.data.get('library_cleanup_queue',[]),[])

    async def test_selection_exhaustion_never_claims_success(self):
        async def no_select(index,model):self.m.client.events.append(('show',index))
        self.m.client.show=no_select
        await self.send();t=await self.finish()
        self.assertEqual(t['stage'],'delivery_exhausted')
        self.assertEqual(len(self.commands('show')),2)
        self.assertEqual(self.m.client.selected,20)

    async def test_download_lost_reply_observes_membership_before_retry(self):
        invoke=self.m.client.invoke
        async def lost_reply(fn,params=None):
            await invoke(fn,params)
            if fn==9601:raise TimeoutError('synthetic private response')
        self.m.client.invoke=lost_reply
        await self.send();t=await self.finish()
        self.assertEqual(t['stage'],'complete')
        self.assertEqual(len(self.commands('download')),1)

    async def test_wake_lost_reply_still_settles_and_uses_same_registration(self):
        invoke=self.m.client.invoke
        async def lost_reply(fn,params=None):
            await invoke(fn,params)
            if fn==9609:raise TimeoutError('lost wake reply')
        self.m.client.invoke=lost_reply
        await self.send();t=await self.finish()
        self.assertEqual(t['stage'],'complete')
        self.assertEqual(len(self.commands('register')),1)
        self.assertEqual(len(self.commands('wake')),1)

    async def test_selection_lost_reply_observes_selection_before_retry(self):
        show=self.m.client.show
        async def lost_reply(index,model):
            await show(index,model);raise TimeoutError('synthetic private response')
        self.m.client.show=lost_reply
        await self.send();t=await self.finish()
        self.assertEqual(t['stage'],'complete');self.assertEqual(len(self.commands('show')),1)

    async def test_registration_lost_reply_never_registers_again(self):
        cloud_art=self.m.cloud_art
        async def ambiguous(content):
            await cloud_art(content)
            self.m.data['pending_cloud_registration']={'sha256':'synthetic'}
            raise TimeoutError('lost receipt')
        self.m.cloud_art=ambiguous
        await self.send();t=await self.finish()
        self.assertEqual(t['stage'],'delivery_error')
        with self.assertRaisesRegex(FrameError,'receipt'):await self.send()
        self.assertEqual(len(self.commands('register')),1);self.assertEqual(self.commands('wake'),[])

    async def test_stale_new_identity_never_downloads_or_selects(self):
        await self.registered();self.m.client.items[21]['id']='reused-slot'
        async with self.m.lock:await self.lib.delivery_step()
        self.assertEqual(self.m.data['library_transaction']['stage'],'delivery_error')
        self.assertEqual(self.commands('wake'),[])
        self.assertEqual(self.commands('download'),[])

    async def test_identity_changed_after_wake_prevents_download(self):
        await self.registered()
        async with self.m.lock:await self.lib.delivery_step()
        self.clock.now+=5;self.m.client.items[21]['id']='reused-after-wake'
        async with self.m.lock:await self.lib.delivery_step()
        self.assertEqual(self.commands('download'),[])

    async def test_failed_persistence_prevents_wake_command(self):
        await self.registered();self.m.fail_save=True
        with self.assertRaises(OSError):
            async with self.m.lock:await self.lib.delivery_step()
        self.assertEqual(self.commands('wake'),[])
        self.assertEqual(self.m.data['library_transaction']['delivery']['download_attempts'],0)

    async def test_failed_download_intent_save_prevents_download(self):
        await self.registered()
        async with self.m.lock:await self.lib.delivery_step()
        self.clock.now+=5;self.m.fail_save=True
        with self.assertRaises(OSError):
            async with self.m.lock:await self.lib.delivery_step()
        self.assertEqual(self.commands('download'),[])

    async def test_poll_releases_lock_one_worker_and_concurrent_same_source(self):
        reached=asyncio.Event();release=asyncio.Event()
        async def pause(delay):
            reached.set();await release.wait();self.clock.now+=delay;await self.real_sleep(0)
        with patch.object(module.asyncio,'sleep',pause):
            await self.send();task=self.m.library_delivery_task
            await asyncio.wait_for(reached.wait(),1)
            self.assertFalse(self.m.lock.locked())
            response=await self.send()
            self.assertTrue(response['pending']);self.assertIs(task,self.m.library_delivery_task)
            with self.assertRaises(FrameError):await self.send(jpeg((4,5,6)))
            release.set();await self.finish()
        self.assertEqual(len(self.commands('register')),1)

    async def test_cancel_during_settle_then_restart_preserves_budget_and_identity(self):
        reached=asyncio.Event();release=asyncio.Event()
        async def pause(delay):
            if delay==5:
                reached.set();await release.wait()
            else:
                self.clock.now+=delay;await self.real_sleep(0)
        with patch.object(module.asyncio,'sleep',pause):
            await self.send()
            await asyncio.wait_for(reached.wait(),1)
            task=self.m.library_delivery_task;task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        saved=copy.deepcopy(self.m.saved[-1])
        self.clock.now+=5
        other=Manager(self.temp.name);other.data=saved;other.client=self.m.client;other.client.m=other
        self.m=other;self.lib=Library(other)
        self.lib.queue_delivery();t=await self.finish()
        self.assertEqual(t['stage'],'complete')
        self.assertEqual(len(self.commands('register')),1)
        self.assertLessEqual(len(self.commands('wake')),2)

    async def test_restart_after_persisted_wake_intent_does_not_duplicate_wake(self):
        await self.registered()
        async with self.m.lock:await self.lib.delivery_step()
        saved=copy.deepcopy(self.m.saved[-1]);self.clock.now+=5
        other=Manager(self.temp.name);other.data=saved;other.client=self.m.client;other.client.m=other
        self.m=other;self.lib=Library(other);self.lib.queue_delivery()
        await self.finish();self.assertEqual(len(self.commands('wake')),1)
        self.assertEqual(len(self.commands('register')),1)

    async def test_restart_registering_without_identity_stops_for_reconciliation(self):
        with patch.object(self.lib,'queue_delivery'):await self.send()
        self.m.data['library_transaction']['stage']='registering'
        self.lib.queue_delivery();t=await self.finish()
        self.assertEqual(t['stage'],'delivery_error');self.assertEqual(self.commands('register'),[])

    async def test_deadline_expiry_sends_no_new_command(self):
        await self.registered();self.clock.now+=601
        async with self.m.lock:await self.lib.delivery_step()
        self.assertEqual(self.m.data['library_transaction']['stage'],'delivery_exhausted')
        self.assertEqual(self.commands('wake'),[])

    async def test_clock_rollback_cannot_extend_delivery_indefinitely(self):
        await self.registered();self.clock.now-=100
        async with self.m.lock:await self.lib.delivery_step()
        self.assertEqual(self.m.data['library_transaction']['stage'],'delivery_error')
        self.assertEqual(self.commands('wake'),[])

    async def test_failed_selection_intent_save_prevents_selection(self):
        await self.registered();self.m.client.stored.add(21);self.m.fail_save=True
        with self.assertRaises(OSError):
            async with self.m.lock:await self.lib.delivery_step()
        self.assertEqual(self.commands('show'),[])

    async def test_restart_after_saved_download_intent_observes_before_resend(self):
        await self.registered()
        async with self.m.lock:await self.lib.delivery_step()
        self.clock.now+=5
        invoke=self.m.client.invoke
        async def cancel_after_download(fn,params=None):
            await invoke(fn,params)
            if fn==9601:raise asyncio.CancelledError()
        self.m.client.invoke=cancel_after_download
        with self.assertRaises(asyncio.CancelledError):
            async with self.m.lock:await self.lib.delivery_step()
        self.m.client.invoke=invoke
        saved=copy.deepcopy(self.m.saved[-1]);other=Manager(self.temp.name)
        other.data=saved;other.client=self.m.client;other.client.m=other
        self.m=other;self.lib=Library(other);self.lib.queue_delivery();await self.finish()
        self.assertEqual(len(self.commands('download')),1)
        self.assertEqual(self.m.client.selected,21)

    async def test_restart_after_selection_sent_never_repeats_verified_selection(self):
        await self.registered();self.m.client.stored.add(21)
        show=self.m.client.show
        async def cancelled(index,model):
            await show(index,model);raise asyncio.CancelledError()
        self.m.client.show=cancelled
        with self.assertRaises(asyncio.CancelledError):
            async with self.m.lock:await self.lib.delivery_step()
        self.m.client.show=show
        saved=copy.deepcopy(self.m.saved[-1]);other=Manager(self.temp.name)
        other.data=saved;other.client=self.m.client;other.client.m=other
        self.m=other;self.lib=Library(other);self.lib.queue_delivery();await self.finish()
        self.assertEqual(len(self.commands('show')),1)

    async def test_ambiguous_other_registration_blocks_existing_delivery(self):
        await self.registered();self.m.data['pending_cloud_registration']={'sha256':'other'}
        async with self.m.lock:await self.lib.delivery_step()
        self.assertEqual(self.m.data['library_transaction']['stage'],'delivery_error')
        self.assertEqual(self.commands('wake'),[])

    async def test_stale_identity_before_selection_prevents_selection(self):
        await self.registered();self.m.client.stored.add(21)
        self.m.client.items[21]['id']='reused-before-selection'
        async with self.m.lock:await self.lib.delivery_step()
        self.assertEqual(self.commands('show'),[])

    async def test_failed_queue_save_keeps_verified_delivery_separate_from_cleanup(self):
        await self.registered();self.m.client.stored.add(21);self.m.client.selected=21
        with patch.object(self.lib,'enqueue_cleanup',side_effect=OSError('queue save failed')):
            async with self.m.lock:await self.lib.delivery_step()
        self.assertEqual(self.m.data['library_transaction']['stage'],'confirmed')
        self.assertTrue(self.lib.delivery_response()['local_storage_verified'])
        self.assertEqual(self.commands('delete'),[])

    async def test_notification_arriving_during_wait_preserves_previous(self):
        await self.registered();self.m.notifications=True
        async with self.m.lock:await self.lib.delivery_step()
        self.assertEqual(self.m.data['library_transaction']['stage'],'delivery_error')
        self.assertEqual(self.commands('wake'),[]);self.assertIn(20,self.m.client.stored)

    async def test_restore_explicit_retention_allows_existing_verified_cleanup(self):
        await self.send();await self.finish()
        self.m.data['library_retained_indices']=[20,31,32]
        with self.assertRaises(FrameError):await self.lib.cleanup()
        await self.lib.set_enabled(True,[31,32])
        self.assertEqual(self.m.data['library_retained_indices'],[31,32])
        for _ in range(5):await self.lib.cleanup()
        self.assertFalse(self.lib.cleanup_pending())
        self.assertNotIn(20,self.m.client.items);self.assertIn(21,self.m.client.stored)
        self.assertTrue(self.m.data['library_cleanup_queue'][0]['previous']['gallery_id'])

    async def test_diagnostics_and_errors_do_not_echo_exception_secrets(self):
        async def broken():raise TimeoutError('PRIVATE_EXCEPTION_TEXT_MUST_NOT_ESCAPE')
        with patch.object(self.lib,'queue_delivery'):await self.send()
        self.m.client.reported_state=broken
        self.lib.queue_delivery();await self.finish()
        text=json.dumps(self.lib.describe(self.m.data['library_transaction']))
        self.assertNotIn('PRIVATE_EXCEPTION_TEXT_MUST_NOT_ESCAPE',text);self.assertNotIn('https:',text)


if __name__=='__main__':unittest.main()
