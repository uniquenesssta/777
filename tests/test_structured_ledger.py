"""P05-01 actual SQLite transactions/backup boundaries on synthetic local files."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from threading import Barrier,Event,Thread
import time
import unittest
from unittest.mock import patch
import uuid
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from quote_core import PriceItem,PriceSnapshot,QuoteSnapshot,NormalLine,DiscountLine,DraftDetails,Amounts
from quote_ledger import Ledger,Principal,LedgerError,Conflict,Forbidden,InvalidDatabase,UnknownCommit
from quote_ledger.backup import Backups,restore_backup,hash_file
from quote_ledger import schema
from quote_files.transactions import file_lock,FileBusy

ADMIN=Principal('manager','admin');SALES=Principal('sales-1','sales');OTHER=Principal('sales-2','sales')
def uid():return str(uuid.uuid4())
def prices(version='v1'):return PriceSnapshot(version,(PriceItem('单件','10.000000000001','4','1',True),))
def quote(version='v1'):return QuoteSnapshot(version,(NormalLine('单件','2'),DiscountLine('90%')))


class StructuredLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='777-p05-ledger-');self.root=Path(self.temp.name)
        self.ledger=Ledger.create(self.root/'账本 中文 #?.sqlite3' if os.name!='nt' else self.root/'账本 中文.sqlite3')
        self.ledger.publish_prices(uid(),ADMIN,prices())
    def tearDown(self):self.temp.cleanup()
    def order(self,actor=SALES):return self.ledger.submit_order(uid(),actor,quote(),DraftDetails('客户','订单','微信'))
    def backups(self,name='backups'):return Backups.create(self.root/name,auxiliary=os.name!='nt')

    def test_integer_cents_and_exact_parameter_snapshot_round_trip(self):
        result=self.order();self.assertEqual((result['income_cents'],result['cost_cents'],result['profit_cents']),('1800','800','1000'))
        with self.ledger.connection(readonly=True) as c:
            lines=c.execute('SELECT * FROM lines ORDER BY sequence').fetchall()
            self.assertEqual(json.loads(lines[0]['normalized_json'])['sale'],'10.000000000001')
            self.assertEqual(lines[1]['income_cents'],-200);self.assertEqual(lines[1]['cost_cents'],0)
            self.assertEqual(c.execute('SELECT typeof(income_cents) FROM orders').fetchone()[0],'integer')
        self.assertEqual(self.ledger.inventory()['counts']['lines'],2)

    def test_duplicate_request_replays_after_price_change_without_duplicate_booking(self):
        request=uid();a=self.ledger.submit_order(request,SALES,quote());self.ledger.publish_prices(uid(),ADMIN,prices('v2'),expected_price_version_id='v1')
        self.assertEqual(self.ledger.submit_order(request,SALES,quote()),a)
        self.assertEqual(self.ledger.inventory()['counts']['orders'],1)
        with self.assertRaises(Conflict):self.ledger.submit_order(uid(),SALES,quote())

    def test_same_request_different_input_operation_or_actor_conflicts(self):
        request=uid();self.ledger.submit_order(request,SALES,quote())
        for actor,snapshot in ((OTHER,quote()),(SALES,replace(quote(),lines=(NormalLine('单件','3'),)))):
            with self.subTest(actor=actor),self.assertRaises(Conflict):self.ledger.submit_order(request,actor,snapshot)
        with self.assertRaises(Conflict):self.ledger.publish_prices(request,ADMIN,prices('v2'))
        self.assertEqual(self.ledger.inventory()['counts']['orders'],1)

    def test_late_line_failure_rolls_back_order_lines_receipt_audit_and_revision(self):
        before=self.ledger.inventory();request=uid();count=[0]
        def fail(phase,c):
            if phase=='line_inserted':
                count[0]+=1
                if count[0]==2:raise OSError('injected second line failure')
        self.ledger.fault=fail
        with self.assertRaises(OSError):self.ledger.submit_order(request,SALES,quote())
        self.ledger.fault=None
        self.assertEqual(self.ledger.inventory(),before);self.assertIsNone(self.ledger.query_request(request,SALES))
        self.ledger.submit_order(request,SALES,quote());self.assertEqual(self.ledger.inventory()['counts']['orders'],1)

    def test_commit_outcome_unknown_is_queryable_and_retry_idempotent(self):
        request=uid()
        def fail(phase,c):
            if phase=='after_commit':raise OSError('reply lost')
        self.ledger.fault=fail
        with self.assertRaises(UnknownCommit) as exc:self.ledger.submit_order(request,SALES,quote())
        self.assertEqual(exc.exception.request_id,request)
        saved=self.ledger.query_request(request,SALES);self.assertIsNotNone(saved)
        self.ledger.fault=None;self.assertEqual(self.ledger.submit_order(request,SALES,quote()),saved)
        self.assertEqual(self.ledger.inventory()['counts']['orders'],1)

    def test_unknown_or_different_schema_never_overwrites_original(self):
        for mode in ('unknown','version','ddl'):
            path=self.root/(mode+'.sqlite3')
            if mode=='unknown':path.write_bytes(b'existing non-database original')
            else:
                db=Ledger.create(path)
                with sqlite3.connect(path) as c:
                    if mode=='version':c.execute('PRAGMA user_version=999')
                    else:c.execute('CREATE TABLE surprise(value TEXT)')
            raw=path.read_bytes()
            with self.subTest(mode=mode),self.assertRaises((InvalidDatabase,sqlite3.DatabaseError)):Ledger(path)
            with self.assertRaises(FileExistsError):Ledger.create(path)
            self.assertEqual(path.read_bytes(),raw)

    def test_raw_sql_cannot_change_or_delete_immutable_business_history(self):
        order=self.order();self.ledger.append_note(uid(),SALES,order['order_id'],'说明',expected_revision=1)
        for table in ('price_versions','lines','notes','requests','audit_events','orders'):
            with self.subTest(table=table),self.ledger.connection() as c,self.assertRaises(sqlite3.IntegrityError):
                c.execute('DELETE FROM '+table)
        with self.ledger.connection() as c,self.assertRaises(sqlite3.IntegrityError):c.execute('UPDATE orders SET income_cents=999')
        self.assertEqual(self.ledger.inventory()['active_income_cents'],'1800')

    def test_note_revision_ownership_and_append_only_replay(self):
        order=self.order();request=uid()
        with self.assertRaises(Forbidden):self.ledger.append_note(uid(),OTHER,order['order_id'],'跨用户',expected_revision=1)
        saved=self.ledger.append_note(request,SALES,order['order_id'],'只追加\n保留原文',expected_revision=1)
        self.assertEqual(self.ledger.append_note(request,SALES,order['order_id'],'只追加\n保留原文',expected_revision=1),saved)
        with self.assertRaises(Conflict):self.ledger.append_note(uid(),SALES,order['order_id'],'旧revision',expected_revision=1)
        with self.assertRaises(Forbidden):self.ledger.query_request(request,OTHER)
        self.assertEqual(self.ledger.inventory()['counts']['notes'],1)

    def test_void_restore_reconciles_active_totals_preserves_every_historical_line(self):
        order=self.order();before=self.ledger.inventory()
        with self.assertRaises(Forbidden):self.ledger.set_state(uid(),SALES,order['order_id'],'void','原因',expected_revision=1)
        self.ledger.set_state(uid(),ADMIN,order['order_id'],'void','作废原因',expected_revision=1)
        self.assertEqual(self.ledger.inventory()['active_income_cents'],'0')
        self.ledger.set_state(uid(),ADMIN,order['order_id'],'active','恢复原因',expected_revision=2)
        current=self.ledger.inventory();self.assertEqual(current['active_income_cents'],before['active_income_cents']);self.assertEqual(current['counts']['lines'],2)

    def test_invalid_order_or_catalog_rejected_without_partial_transaction(self):
        before=self.ledger.inventory()
        with self.assertRaises(LedgerError):self.ledger.submit_order(uid(),SALES,replace(quote(),lines=(NormalLine('单件','bad'),)))
        with self.assertRaises(LedgerError):self.ledger.publish_prices(uid(),ADMIN,PriceSnapshot('bad',(PriceItem('单件','NaN','4','1',True),)))
        with self.assertRaises(Forbidden):self.ledger.publish_prices(uid(),SALES,prices('v2'))
        self.assertEqual(self.ledger.inventory(),before)

    def test_active_price_reference_cannot_point_to_nonexistent_version(self):
        before=self.ledger.inventory()
        with self.ledger.connection() as c,self.assertRaises(sqlite3.IntegrityError):
            c.execute("UPDATE ledger_meta SET active_price_id='missing'")
        self.assertEqual(self.ledger.inventory(),before)

    def test_price_publication_compare_and_swap_rejects_stale_manager(self):
        request=uid();published=self.ledger.publish_prices(request,ADMIN,prices('v2'),expected_price_version_id='v1')
        before=self.ledger.inventory()
        with self.assertRaises(Conflict):self.ledger.publish_prices(uid(),ADMIN,prices('v3'),expected_price_version_id='v1')
        self.assertEqual(self.ledger.publish_prices(request,ADMIN,prices('v2'),expected_price_version_id='v1'),published)
        self.assertEqual(self.ledger.inventory(),before)

    def test_two_connections_same_request_converge_to_one_atomic_order(self):
        request=uid();barrier=Barrier(3);results=[];errors=[]
        def submit():
            try:
                instance=Ledger(self.ledger.path);barrier.wait();results.append(instance.submit_order(request,SALES,quote()))
            except BaseException as exc:errors.append(exc)
        workers=[Thread(target=submit) for _ in range(2)]
        for worker in workers:worker.start()
        barrier.wait()
        for worker in workers:worker.join(5);self.assertFalse(worker.is_alive())
        self.assertEqual(errors,[]);self.assertEqual(results[0],results[1]);self.assertEqual(self.ledger.inventory()['counts']['orders'],1)

    def test_sqlite_busy_has_no_partial_effect_and_can_be_explicitly_retried(self):
        request=uid();other=Ledger(self.ledger.path,timeout=.01)
        with self.ledger.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            with self.assertRaises(sqlite3.OperationalError):other.submit_order(request,SALES,quote())
            c.execute('ROLLBACK')
        self.assertIsNone(other.query_request(request,SALES));other.submit_order(request,SALES,quote())
        self.assertEqual(self.ledger.inventory()['counts']['orders'],1)

    def test_local_path_gate_rejects_unc_relative_uri_and_symlink_ancestor(self):
        from quote_ledger.paths import local_path
        for value in ('relative.sqlite3',':memory:','file:db.sqlite3',r'\\server\share\db.sqlite3'):
            with self.subTest(value=value),self.assertRaises(LedgerError):local_path(value,exists=False)
        if os.name!='nt':
            link=self.root/'link';link.symlink_to(self.root,target_is_directory=True)
            with self.assertRaises(LedgerError):Ledger.create(link/'db.sqlite3')

    def test_backup_restores_notes_receipts_void_history_and_price_versions(self):
        order=self.order();self.ledger.append_note(uid(),SALES,order['order_id'],'备注',expected_revision=1)
        self.ledger.set_state(uid(),ADMIN,order['order_id'],'void','原因',expected_revision=2)
        self.ledger.publish_prices(uid(),ADMIN,prices('v2'),expected_price_version_id='v1');manager=self.backups();entry=manager.create_backup(self.ledger)
        restored=restore_backup(manager.root/entry['backup_id'],self.root/'独立恢复.sqlite3')
        self.assertEqual(restored.inventory(),self.ledger.inventory());self.assertEqual(restored.inventory()['counts']['notes'],1)
        request=uid();restored.submit_order(request,SALES,quote('v2'));self.assertIsNone(self.ledger.query_request(request,SALES))
        with self.assertRaises(LedgerError):restore_backup(manager.root/entry['backup_id'],self.ledger.path)

    def test_each_writer_and_independent_restore_use_wal_and_full_durability(self):
        manager=self.backups();entry=manager.create_backup(self.ledger)
        restored=restore_backup(manager.root/entry['backup_id'],self.root/'durability.sqlite3')
        for ledger in (self.ledger,restored):
            with ledger.connection() as c:
                self.assertEqual(c.execute('PRAGMA journal_mode').fetchone()[0],'wal')
                self.assertEqual(c.execute('PRAGMA synchronous').fetchone()[0],2)

    def test_backup_after_live_writer_keeps_consistent_snapshot_and_all_rows(self):
        manager=self.backups();started=Event();release=Event();errors=[]
        def write():
            try:
                instance=Ledger(self.ledger.path)
                def fault(phase,c):
                    if phase=='before_commit':started.set();release.wait(3)
                instance.fault=fault;instance.submit_order(uid(),SALES,quote())
            except BaseException as exc:errors.append(exc)
        worker=Thread(target=write);worker.start();self.assertTrue(started.wait(3))
        try:entry=manager.create_backup(self.ledger)
        finally:release.set();worker.join(5)
        self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
        restored=restore_backup(manager.root/entry['backup_id'],self.root/'concurrent.sqlite3')
        self.assertEqual(restored.inventory()['counts']['orders'],0);self.assertEqual(self.ledger.inventory()['counts']['orders'],1)

    def test_backup_timeout_or_publish_failure_preserves_last_verified_success(self):
        self.order();manager=self.backups();first=manager.create_backup(self.ledger);before=manager.status()
        with self.assertRaises(LedgerError):manager.create_backup(self.ledger,timeout=-1)
        after=manager.status();self.assertEqual(after['last_success'],first);self.assertIsNotNone(after['last_error']);self.assertEqual(after['backups'],before['backups'])
        restored=restore_backup(manager.root/first['backup_id'],self.root/'after-failure.sqlite3');self.assertEqual(restored.inventory(),self.ledger.inventory())

    def test_retention_keeps_maintenance_latest_and_unknown_files(self):
        manager=self.backups();when=datetime(2026,1,1,tzinfo=timezone.utc)
        first=manager.create_backup(self.ledger,clock=when);maintenance=manager.create_backup(self.ledger,kind='maintenance',clock=when)
        latest=manager.create_backup(self.ledger,clock=when+timedelta(hours=1));unknown=manager.root/'unknown.txt';unknown.write_text('leave alone')
        removed=manager.retain(rolling=1,daily=1)
        self.assertEqual(removed,[first['backup_id']]);self.assertTrue((manager.root/maintenance['backup_id']).exists());self.assertTrue((manager.root/latest['backup_id']).exists());self.assertEqual(unknown.read_text(),'leave alone')

    def test_scheduler_due_policy_and_native_owner_lock_are_single_writer(self):
        manager=self.backups();when=datetime(2026,1,1,1,tzinfo=timezone.utc)
        first=manager.run_due(self.ledger,now=when);self.assertIsNotNone(first)
        self.assertIsNone(manager.run_due(self.ledger,now=when+timedelta(minutes=31)))
        self.order();self.assertIsNone(manager.run_due(self.ledger,now=when+timedelta(minutes=10)))
        self.assertIsNotNone(manager.run_due(self.ledger,now=when+timedelta(minutes=31)))
        daily=manager.run_due(self.ledger,now=when+timedelta(hours=1));self.assertEqual(daily['kind'],'daily')
        with file_lock(manager.root/'scheduler'),self.assertRaises(FileBusy):manager.run_due(self.ledger,now=when+timedelta(hours=2))

    def test_tampered_backup_hash_refuses_restore_without_target_or_source_damage(self):
        manager=self.backups();entry=manager.create_backup(self.ledger);folder=manager.root/entry['backup_id'];database=folder/'ledger.sqlite3';database.write_bytes(database.read_bytes()+b'changed')
        target=self.root/'must-not-exist.sqlite3'
        with self.assertRaises(InvalidDatabase):restore_backup(folder,target)
        self.assertFalse(target.exists());self.assertEqual(self.ledger.inventory()['counts']['orders'],0)

    def test_database_content_semantics_checked_before_backup_not_only_sql_integrity(self):
        order=self.order()
        # Model an independently altered data file, retaining expected schema.
        with self.ledger.connection() as c:
            c.execute('DROP TRIGGER orders_immutable')
            c.execute('UPDATE orders SET income_cents=income_cents+1,profit_cents=profit_cents+1')
            c.execute(schema.DDL[12])
        with self.assertRaises(InvalidDatabase):self.ledger.inventory()
        manager=self.backups()
        with self.assertRaises(InvalidDatabase):manager.create_backup(self.ledger)
        self.assertIsNone(manager.status()['last_success'])

    def test_existing_unowned_backup_folder_is_never_adopted_or_modified(self):
        folder=self.root/'unowned';folder.mkdir();marker=folder/'original.txt';marker.write_text('preserve')
        with self.assertRaises(FileExistsError):Backups.create(folder,auxiliary=os.name!='nt')
        self.assertEqual(marker.read_text(),'preserve');self.assertEqual(list(folder.iterdir()),[marker])

    def test_process_exit_inside_transaction_recovers_without_half_order(self):
        request=uid()
        code='''import os,sys\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\nfrom quote_ledger import Ledger,Principal\nfrom quote_core import QuoteSnapshot,NormalLine\ndef fail(phase,connection):\n if phase=="before_commit":os._exit(17)\nledger=Ledger(Path(sys.argv[2]),fault=fail)\nledger.submit_order(sys.argv[3],Principal("sales-1","sales"),QuoteSnapshot("v1",(NormalLine("单件","2"),)))\n'''
        result=subprocess.run([sys.executable,'-c',code,str(ROOT),str(self.ledger.path),request],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,17,result.stderr)
        self.assertIsNone(self.ledger.query_request(request,SALES));self.assertEqual(self.ledger.inventory()['counts']['orders'],0)
        self.ledger.submit_order(request,SALES,quote());self.assertEqual(self.ledger.inventory()['counts']['orders'],1)

    def test_existing_sidecars_and_linked_sidecars_are_never_overwritten(self):
        target=self.root/'occupied.sqlite3';sidecar=Path(str(target)+'-wal');sidecar.write_bytes(b'foreign original')
        with self.assertRaises(FileExistsError):Ledger.create(target)
        self.assertFalse(target.exists());self.assertEqual(sidecar.read_bytes(),b'foreign original')
        manager=self.backups();entry=manager.create_backup(self.ledger)
        with self.assertRaises(LedgerError):restore_backup(manager.root/entry['backup_id'],target)
        self.assertFalse(target.exists());self.assertEqual(sidecar.read_bytes(),b'foreign original')

    def test_static_golden_cases_persist_exact_valid_results_and_reject_invalid_ones(self):
        from test_quote_core import SUITE,golden_inputs
        from decimal import Decimal
        self.assertEqual(len(SUITE['cases']),53)
        for case in SUITE['cases']:
            with self.subTest(case=case['id']):
                snapshot,catalog=golden_inputs(case);db=Ledger.create(self.root/(uid()+'.sqlite3'))
                try:db.publish_prices(uid(),ADMIN,catalog)
                except LedgerError:
                    self.assertNotEqual(case['expected']['status'],'ok');self.assertEqual(db.inventory()['counts']['orders'],0);continue
                if case['expected']['status']=='ok':
                    result=db.submit_order(uid(),SALES,snapshot)
                    target=case['expected']['totals'];self.assertEqual(result['income_cents'],str(int(Decimal(target['income'])*100)));self.assertEqual(result['cost_cents'],str(int(Decimal(target['cost'])*100)))
                    self.assertEqual(db.inventory()['counts']['lines'],len(snapshot.lines))
                else:
                    with self.assertRaises(LedgerError):db.submit_order(uid(),SALES,snapshot)
                    self.assertEqual(db.inventory()['counts']['orders'],0)


if __name__=='__main__':unittest.main()
