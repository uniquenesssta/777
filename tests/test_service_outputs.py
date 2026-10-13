"""Durable output behavior with real SQLite/files/HTTPS; no production paths."""
from dataclasses import asdict
import base64
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from quote_core import PriceSnapshot,PriceItem,QuoteSnapshot,NormalLine,DiscountLine,DraftDetails
from quote_service.hosting import initialize,load,enable_outputs
from quote_service.output_render import FORMAT,render
from quote_service.outputs import Outputs,publish
from quote_service.protocol import APIError
from quote_service.recovery import restore,manifest
from quote_service.journal import MemoryJournal
from quote_service.client import CommitUnknown
from quote_ledger import Conflict
from quote_app.service_client import save_output_content
from service_fixture import Hosted


def uid():return str(uuid.uuid4())


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        initialize(self.root/'host',self.root/'backups','manager','fixture-password-123',hosts=['localhost'],auxiliary=os.name!='nt')
        _,_,self.service=load(self.root/'host',auxiliary=os.name!='nt')
        self.auth=self.service.auth
        self.login=self.auth.login('manager','fixture-password-123','fixture');self.actor=self.auth.authenticate(self.login['token'])
        self.sales_user=self.auth.create_account(self.actor,'sales','fixture-password-123','sales')
        self.sales_login=self.auth.login('sales','fixture-password-123','fixture');self.sales=self.auth.authenticate(self.sales_login['token'])
        self.service.ledger.publish_prices(uid(),self.actor,PriceSnapshot('v1',(PriceItem('single','10','4','1',True),)))
        self.snapshot=QuoteSnapshot('v1',(NormalLine('single','4'),DiscountLine('90%')))
        self.order=self.service.ledger.submit_order(uid(),self.sales,self.snapshot,DraftDetails('=HYPERLINK("evil")','000123','wechat'))
        self.outputs=self.service.outputs
    def tearDown(self):self.temp.cleanup()
    def request(self,kind='excel_quote',actor=None,key=None,revision=1):
        actor=actor or self.sales
        return self.service.output_task(actor,dict(request_id=key or uid(),order_id=self.order['order_id'],expected_revision=revision,kind=kind,format=FORMAT))
    def configure(self):
        (self.root/'reports').mkdir(exist_ok=True);(self.root/'images').mkdir(exist_ok=True)
        # Only the auxiliary/local native fixture injects temp output directories.
        with self.auth.connection() as c:
            c.execute('UPDATE preferences SET export_dir=?,image_dir=?,revision=revision+1 WHERE id=1',(str(self.root/'reports'),str(self.root/'images')))
    def workbook(self,key):
        from openpyxl import load_workbook
        value=self.outputs.content(self.actor,key)
        return load_workbook(io.BytesIO(base64.b64decode(value['data_base64'])),data_only=False)

    def test_output_enqueue_and_duplicate_do_not_write_financial_ledger(self):
        before=self.service.ledger.inventory();key=uid();first=self.request(key=key)
        self.assertEqual(self.request(key=key),first);self.assertEqual(self.service.ledger.inventory(),before)
        self.assertEqual(first['state'],'queued')
        with self.outputs.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM jobs').fetchone()[0],1)

    def test_same_request_changed_kind_revision_or_actor_is_refused(self):
        key=uid();self.request(key=key)
        for changes in [{'kind':'quote_png'},{'expected_revision':2}]:
            with self.subTest(changes=changes),self.assertRaises(Conflict):
                self.service.output_task(self.sales,dict(request_id=key,order_id=self.order['order_id'],expected_revision=1,kind='excel_quote',format=FORMAT)|changes)
        with self.assertRaises(Conflict):self.request(actor=self.actor,key=key)

    def test_sales_other_owner_and_internal_report_are_denied(self):
        other=self.auth.create_account(self.actor,'other','fixture-password-123','sales')
        login=self.auth.login('other','fixture-password-123','fixture');actor=self.auth.authenticate(login['token'])
        with self.assertRaises(APIError):self.request(actor=actor)
        with self.assertRaises(APIError):self.request(kind='excel_admin')
        private=self.request(kind='excel_admin',actor=self.actor)
        for method in [self.outputs.status,self.outputs.content]:
            with self.assertRaises(APIError):method(self.sales,private['job_id'])

    def test_public_workbook_is_exact_role_filtered_and_formula_free(self):
        self.configure();task=self.request();self.outputs.run_one(self.service)
        self.assertEqual(self.outputs.status(self.sales,task['job_id'])['state'],'done')
        w=self.workbook(task['job_id'])
        try:
            data=dict(list(w['Order'].values)[1:]);self.assertEqual(data['income_cents'],'3600');self.assertEqual(data['order_ref'],'000123')
            self.assertEqual(data['customer'],'=HYPERLINK("evil")');self.assertNotIn('cost_cents',data);self.assertNotIn('profit_cents',data)
            all_text=' '.join(str(cell.value) for ws in w for row in ws for cell in row)
            self.assertNotIn('"cost"',all_text)
            self.assertTrue(all(cell.data_type!='f' for ws in w for row in ws for cell in row))
        finally:w.close()
        self.assertEqual(len(list((self.root/'reports').glob('*.xlsx'))),1)

    def test_admin_public_report_also_excludes_cost_but_internal_stays_private(self):
        self.configure();public=self.request(actor=self.actor);private=self.request(kind='excel_admin',actor=self.actor)
        self.outputs.run_one(self.service);self.outputs.run_one(self.service)
        for task,has_cost in [(public,False),(private,True)]:
            w=self.workbook(task['job_id'])
            try:
                data=dict(list(w['Order'].values)[1:]);self.assertEqual('cost_cents' in data,has_cost)
                if has_cost:self.assertEqual((data['cost_cents'],data['profit_cents']),('1600','2000'))
            finally:w.close()
        self.assertEqual(len(list((self.root/'reports').glob('*.xlsx'))),1)

    def test_missing_directory_keeps_order_and_cached_bytes_retry_uses_new_published_directory(self):
        before=self.service.ledger.inventory();task=self.request();self.outputs.run_one(self.service)
        first=self.outputs.status(self.sales,task['job_id']);self.assertEqual(first['state'],'failed');self.assertEqual(first['error'],'OUTPUT_DIRECTORY_NOT_PUBLISHED')
        raw=self.outputs.content(self.sales,task['job_id']);self.configure()
        retry=uid();self.outputs.retry(self.sales,task['job_id'],retry)
        self.assertEqual(self.outputs.retry(self.sales,task['job_id'],retry)['request_id'],retry)
        with patch('quote_service.outputs.render',side_effect=AssertionError('must reuse existing bytes')):self.outputs.run_one(self.service)
        self.assertEqual(self.outputs.status(self.sales,task['job_id'])['blob_sha256'],first['blob_sha256'])
        self.assertEqual(self.outputs.content(self.sales,task['job_id']),raw);self.assertEqual(self.service.ledger.inventory(),before)

    def test_excel_permission_failure_retry_never_books_or_changes_original_order(self):
        self.configure();task=self.request();before=self.service.ledger.inventory()
        with patch('quote_service.outputs.publish',side_effect=PermissionError('password/token/private-customer must not escape')):self.outputs.run_one(self.service)
        failed=self.outputs.status(self.sales,task['job_id']);self.assertEqual(failed['error'],'OUTPUT_IO_FAILED:PermissionError')
        self.assertNotIn('password',json.dumps(failed));self.outputs.retry(self.sales,task['job_id'],uid());self.outputs.run_one(self.service)
        self.assertEqual(self.outputs.status(self.sales,task['job_id'])['state'],'done');self.assertEqual(self.service.ledger.inventory(),before)

    def test_foreign_existing_file_is_not_overwritten(self):
        self.configure();task=self.request();target=self.root/'reports'/('777-'+self.order['order_id']+'-'+task['job_id']+'.xlsx');target.write_bytes(b'foreign')
        self.outputs.run_one(self.service);self.assertEqual(target.read_bytes(),b'foreign');self.assertEqual(self.outputs.status(self.sales,task['job_id'])['error'],'OUTPUT_FILE_CONFLICT')

    def test_publish_failure_leaves_no_partial_or_claim_of_done(self):
        self.configure();task=self.request()
        def interrupted(origin,stream):stream.write(origin.read(10));raise OSError('copy interrupted')
        with patch('quote_service.outputs.copy_output',side_effect=interrupted):self.outputs.run_one(self.service)
        self.assertEqual(list((self.root/'reports').iterdir()),[]);self.assertEqual(self.outputs.status(self.sales,task['job_id'])['state'],'failed')

    def test_reply_or_process_loss_after_publish_recovers_same_file_without_duplication(self):
        self.configure();task=self.request()
        class Crash(BaseException):pass
        def fault(step):
            if step=='published':raise Crash()
        with self.assertRaises(Crash):self.outputs.run_one(self.service,fault=fault)
        self.assertEqual(self.outputs.status(self.sales,task['job_id'])['state'],'running')
        reopened=Outputs(self.outputs.path,self.outputs.ledger_id);reopened.recover();reopened.run_one(self.service)
        self.assertEqual(reopened.status(self.sales,task['job_id'])['state'],'done');self.assertEqual(len(list((self.root/'reports').iterdir())),1)

    def test_restart_reopens_original_failed_queue_and_cached_blob(self):
        task=self.request();self.outputs.run_one(self.service)
        _,_,reopened=load(self.root/'host',auxiliary=os.name!='nt')
        self.assertEqual(reopened.outputs.status(self.sales,task['job_id']),self.outputs.status(self.sales,task['job_id']))
        self.configure();reopened.outputs.retry(self.sales,task['job_id'],uid());reopened.outputs.run_one(reopened)
        self.assertEqual(reopened.outputs.status(self.sales,task['job_id'])['state'],'done')

    def test_later_note_state_and_price_do_not_rewrite_original_output_snapshot(self):
        self.configure();task=self.request();self.outputs.run_one(self.service);original=self.outputs.content(self.sales,task['job_id'])
        self.service.ledger.append_note(uid(),self.sales,self.order['order_id'],'later',expected_revision=1)
        self.service.ledger.set_state(uid(),self.actor,self.order['order_id'],'void','reason',expected_revision=2)
        self.service.ledger.publish_prices(uid(),self.actor,PriceSnapshot('v2',(PriceItem('single','99','55','1',True),)),expected_price_version_id='v1')
        self.outputs.retry(self.sales,task['job_id'],uid());self.outputs.run_one(self.service)
        self.assertEqual(self.outputs.content(self.sales,task['job_id']),original)
        with self.assertRaises(APIError):self.request(revision=1)
        self.assertEqual(self.request(revision=3)['order_revision'],3)

    def test_revoked_or_changed_role_account_job_cannot_be_published(self):
        self.configure();task=self.request();self.auth.update_account(self.actor,self.sales.subject,enabled=False)
        self.outputs.run_one(self.service);self.assertEqual(self.outputs.status(self.actor,task['job_id'])['error'],'OUTPUT_ACCOUNT_CHANGED');self.assertEqual(list((self.root/'reports').iterdir()),[])

    def test_blob_tamper_and_link_are_refused(self):
        self.configure();task=self.request();self.outputs.run_one(self.service)
        path=self.root/'host/private/output-blobs'/(task['job_id']+'.xlsx');path.write_bytes(b'changed')
        with self.assertRaises(APIError):self.outputs.content(self.sales,task['job_id'])
        if os.name!='nt':
            path.unlink();path.symlink_to(self.root/'backups')
            with self.assertRaises(Exception):self.outputs.content(self.sales,task['job_id'])

    def test_snapshot_payload_and_receipt_are_immutable(self):
        task=self.request()
        import sqlite3
        with self.outputs.connection() as c:
            for sql in ["UPDATE jobs SET payload_json='{}'","UPDATE receipts SET result_json='{}'","DELETE FROM receipts"]:
                with self.subTest(sql=sql),self.assertRaises(sqlite3.IntegrityError):c.execute(sql)

    def test_output_queue_bound_and_format_negotiation_reject_before_write(self):
        before=self.service.ledger.inventory()
        with self.assertRaises(APIError):self.service.output_task(self.sales,dict(request_id=uid(),order_id=self.order['order_id'],expected_revision=1,kind='excel_quote',format='future-v2'))
        for _ in range(64):self.request()
        with self.assertRaises(APIError) as caught:self.request()
        self.assertEqual(caught.exception.code,'OUTPUT_QUEUE_FULL');self.assertEqual(self.service.ledger.inventory(),before)

    def test_png_is_based_on_saved_order_and_has_payload_metadata(self):
        self.configure();task=self.request('quote_png');self.outputs.run_one(self.service)
        self.assertEqual(self.outputs.status(self.sales,task['job_id'])['state'],'done')
        from PIL import Image
        with Image.open(io.BytesIO(base64.b64decode(self.outputs.content(self.sales,task['job_id'])['data_base64']))) as image:
            self.assertEqual(image.format,'PNG');self.assertEqual(image.info['777_format'],FORMAT);self.assertEqual(image.info['777_job_id'],task['job_id'])

    def test_backup_v2_restores_queue_original_files_and_receipts_in_maintenance(self):
        self.configure();done=self.request();self.outputs.run_one(self.service);queued=self.request('excel_admin',self.actor)
        before=self.service.ledger.inventory();entry=self.service.backup(kind='maintenance');value=manifest(entry['service_bundle']);self.assertEqual(value['format'],'777-service-bundle-v2')
        target=self.root/'restore';restore(entry['service_bundle'],target,'manager','new-fixture-password',auxiliary=os.name!='nt')
        _,config,reopened=load(target,auxiliary=os.name!='nt',allow_maintenance=True)
        self.assertTrue(config['maintenance']);self.assertEqual(reopened.ledger.inventory(),before)
        self.assertEqual(reopened.outputs.content(self.actor,done['job_id']),self.outputs.content(self.actor,done['job_id']))
        self.assertEqual(reopened.outputs.status(self.actor,queued['job_id'])['state'],'queued')
        self.assertEqual(reopened.outputs.receipt(self.actor,done['request_id'])['job_id'],done['job_id'])

    def test_backup_v1_remains_readable_without_silent_output_creation(self):
        self.service.outputs=None;entry=self.service.backup(kind='maintenance');self.assertEqual(manifest(entry['service_bundle'])['format'],'777-service-bundle-v1')
        restore(entry['service_bundle'],self.root/'old-restored','manager','new-fixture-password',auxiliary=os.name!='nt')
        _,_,reopened=load(self.root/'old-restored',auxiliary=os.name!='nt',allow_maintenance=True)
        self.assertIsNone(reopened.outputs);self.assertFalse((self.root/'old-restored/private/outputs.sqlite3').exists())

    def test_unknown_output_schema_refused_without_repair_or_overwrite(self):
        with self.outputs.connection() as c:c.execute('PRAGMA user_version=99')
        raw=self.outputs.path.read_bytes()
        with self.assertRaises(APIError):Outputs(self.outputs.path,self.outputs.ledger_id)
        self.assertEqual(self.outputs.path.read_bytes(),raw)

    def test_legacy_host_activation_requires_admin_owner_lock_and_complete_backup(self):
        (self.root/'host/private/outputs.sqlite3').unlink();(self.root/'host/private/output-blobs').rmdir()
        with self.assertRaises(APIError):enable_outputs(self.root/'host','sales','fixture-password-123',auxiliary=os.name!='nt')
        self.assertFalse((self.root/'host/private/outputs.sqlite3').exists())
        result=enable_outputs(self.root/'host','manager','fixture-password-123',auxiliary=os.name!='nt')
        self.assertTrue(result['ledger_schema_unchanged'])

    def test_download_new_copy_verifies_bytes_and_cannot_replace_existing_file(self):
        self.configure();task=self.request();self.outputs.run_one(self.service);data=self.outputs.content(self.sales,task['job_id'])
        target=self.root/'copy.xlsx';self.assertTrue(save_output_content(data,target)['saved'])
        with self.assertRaises(FileExistsError):save_output_content(data,target)
        with self.assertRaises(APIError):save_output_content(data|{'sha256':'0'*64},self.root/'bad.xlsx')
        self.assertFalse((self.root/'bad.xlsx').exists())

    def test_corrupt_output_blob_prevents_new_complete_backup_success(self):
        self.configure();task=self.request();self.outputs.run_one(self.service)
        first=self.service.backup(kind='maintenance');before=self.service.ledger.inventory()
        (self.root/'host/private/output-blobs'/(task['job_id']+'.xlsx')).write_bytes(b'changed')
        with self.assertRaises(APIError):self.service.backup(kind='maintenance')
        self.assertEqual(self.auth.backup_health()['last_success'],first);self.assertEqual(self.service.ledger.inventory(),before)

    def test_existing_host_extension_backup_failure_creates_no_output_store(self):
        (self.root/'host/private/outputs.sqlite3').unlink();(self.root/'host/private/output-blobs').rmdir()
        before=self.service.ledger.inventory()
        with patch('quote_service.app.Service.backup',side_effect=OSError('isolated backup failure')),self.assertRaises(OSError):enable_outputs(self.root/'host','manager','fixture-password-123',auxiliary=os.name!='nt')
        self.assertFalse((self.root/'host/private/outputs.sqlite3').exists());self.assertEqual(self.service.ledger.inventory(),before)


class OutputHTTPS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.host=Hosted()
    @classmethod
    def tearDownClass(cls):cls.host.close()
    def setUp(self):self.sales=self.host.client();self.admin=self.host.client('manager')
    def test_actual_service_worker_and_journal_receipt_recovery_do_not_repeat_orders(self):
        import time
        h=self.host;journal=MemoryJournal();order=self.sales.submit(QuoteSnapshot('fixture-v1',(NormalLine('单件','2'),)),DraftDetails(),journal)
        (h.root/'reports').mkdir(exist_ok=True);(h.root/'images').mkdir(exist_ok=True)
        with h.service.auth.connection() as c:c.execute('UPDATE preferences SET export_dir=?,image_dir=? WHERE id=1',(str(h.root/'reports'),str(h.root/'images')))
        before=h.service.ledger.inventory();original=self.sales.request
        def lost(method,path,data=None):
            value=original(method,path,data)
            if method=='POST' and path=='/v1/outputs':raise OSError('lost output reply')
            return value
        with patch.object(self.sales,'request',side_effect=lost),self.assertRaises(CommitUnknown):
            self.sales.mutate('/v1/outputs',dict(order_id=order['order_id'],expected_revision=1,kind='excel_quote',format=FORMAT),journal)
        key=journal.read()['body']['request_id'];receipt=self.sales.check_pending(journal)
        self.assertEqual(receipt['result']['job_id'],key);self.assertIsNone(journal.read())
        for _ in range(300):
            status=self.sales.request('GET','/v1/outputs/'+key)
            if status['state'] in {'done','failed'}:break
            time.sleep(0.02)
        self.assertEqual(status['state'],'done');self.assertEqual(h.service.ledger.inventory(),before)
        self.assertEqual(self.sales.request('GET','/v1/outputs/'+key+'/content')['sha256'],status['blob_sha256'])
        self.sales.mutate('/v1/outputs/'+key+'/retry',{},journal)
        self.assertEqual(h.service.ledger.inventory(),before)

    def test_http_output_wrong_owner_version_and_forged_fields_are_rejected(self):
        order=self.sales.submit(QuoteSnapshot('fixture-v1',(NormalLine('单件','1'),)),DraftDetails(),MemoryJournal())
        data=dict(request_id=uid(),order_id=order['order_id'],expected_revision=1,kind='excel_quote',format=FORMAT)
        for changed in [data|{'owner_id':self.admin.subject},data|{'format':'future'},data|{'output_dir':'arbitrary'},data|{'income_cents':'0'}]:
            with self.assertRaises(APIError):self.sales.request('POST','/v1/outputs',changed)
        other=self.host.client('sales-two')
        with self.assertRaises(APIError):other.request('POST','/v1/outputs',data)
        self.assertEqual(self.sales.request('GET','/v1/capabilities')['cents_encoding'],'decimal-string')

    def test_request_id_cannot_cross_financial_and_output_namespaces(self):
        journal=MemoryJournal();order=self.sales.submit(QuoteSnapshot('fixture-v1',(NormalLine('单件','1'),)),DraftDetails(),journal)
        data=dict(request_id=order['request_id'],order_id=order['order_id'],expected_revision=1,kind='excel_quote')
        with self.assertRaises(APIError):self.sales.request('POST','/v1/outputs',data)
        data['request_id']=uid();task=self.sales.request('POST','/v1/outputs',data)
        with self.assertRaises(APIError):self.sales.request('POST','/v1/orders',{'request_id':task['request_id'],'snapshot':asdict(QuoteSnapshot('fixture-v1',(NormalLine('单件','1'),))),'details':asdict(DraftDetails())})

    def test_two_real_https_clients_same_output_request_converge_to_one_job(self):
        from threading import Thread,Barrier
        order=self.sales.submit(QuoteSnapshot('fixture-v1',(NormalLine('单件','1'),)),DraftDetails(),MemoryJournal())
        other=self.host.client();data=dict(request_id=uid(),order_id=order['order_id'],expected_revision=1,kind='excel_quote',format=FORMAT)
        before=self.host.service.ledger.inventory();barrier=Barrier(3);results=[];errors=[]
        def send(client):
            try:barrier.wait();results.append(client.request('POST','/v1/outputs',data))
            except Exception as exc:errors.append(type(exc).__name__)
        threads=[Thread(target=send,args=(client,)) for client in [self.sales,other]]
        for thread in threads:thread.start()
        barrier.wait()
        for thread in threads:thread.join(10);self.assertFalse(thread.is_alive())
        self.assertEqual(errors,[]);self.assertEqual(results[0],results[1]);self.assertEqual(self.host.service.ledger.inventory(),before)
        with self.host.service.outputs.connection(readonly=True) as c:self.assertEqual(c.execute('SELECT count(*) FROM jobs WHERE job_id=?',(data['request_id'],)).fetchone()[0],1)
