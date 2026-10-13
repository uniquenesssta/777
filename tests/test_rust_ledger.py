"""P06-02 real native-process/SQLite transaction and cross-backend compatibility."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import unittest
import uuid
from quote_core import PriceItem,PriceSnapshot,QuoteSnapshot,NormalLine,DraftDetails
from quote_ledger import Ledger,Principal
from quote_ledger.paths import UnknownCommit,Conflict,Forbidden,InvalidDatabase,LedgerError
from quote_service.rust_ledger import RustLedger
from quote_ledger.backup import Backups,restore_backup
from quote_import.adapters import preview_bytes
from quote_import.store import apply_source,verify_provenance
from import_fixture import current_book
ROOT=Path(__file__).resolve().parents[1]
BINARY=ROOT/'target/release'/('quote-ledger.exe' if os.name=='nt' else 'quote-ledger')
ADMIN=Principal('admin','admin');SALES=Principal('sales','sales');OTHER=Principal('other','sales')
def rid():return str(uuid.uuid4())
def prices(version='v1',sale='10'):return PriceSnapshot(version,(PriceItem('P',sale,'4','',True),))
def quote(version='v1',quantity='2'):return QuoteSnapshot(version,(NormalLine('P',quantity),))

class RustLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='777-p06-ledger-');self.root=Path(self.temp.name)
        self.ledger=RustLedger.create(self.root/'ledger.sqlite3',BINARY,auxiliary=os.name!='nt')
        self.ledger.publish_prices(rid(),ADMIN,prices())
    def tearDown(self):self.temp.cleanup()
    def order(self):return self.ledger.submit_order(rid(),SALES,quote(),DraftDetails('000012','00003','微信'))
    def test_native_schema_and_all_frozen_snapshots_match_python_reader(self):
        self.order();self.assertEqual(self.ledger.inventory(),Ledger(self.ledger.path).inventory())
        with self.ledger.connection(readonly=True) as c:
            self.assertEqual(c.execute('PRAGMA application_id').fetchone()[0],0x3737374c)
            self.assertEqual(c.execute('SELECT details_json FROM orders').fetchone()[0],'{'+'"customer":"000012","order_ref":"00003","wechat":"微信"}')
    def test_request_fingerprint_and_replay_are_equal_in_both_directions(self):
        request=rid();native=self.ledger.submit_order(request,SALES,quote())
        self.assertEqual(Ledger(self.ledger.path).submit_order(request,SALES,quote()),native)
        request=rid();python=Ledger(self.ledger.path).submit_order(request,SALES,quote())
        self.assertEqual(self.ledger.submit_order(request,SALES,quote()),python)
        for actor,q in [(OTHER,quote()),(SALES,quote(quantity='3'))]:
            with self.assertRaises(Conflict):self.ledger.submit_order(request,actor,q)
    def test_same_request_after_price_change_returns_original_receipt(self):
        key=rid();order=self.ledger.submit_order(key,SALES,quote())
        self.ledger.publish_prices(rid(),ADMIN,prices('v2','12'),expected_price_version_id='v1')
        self.assertEqual(self.ledger.submit_order(key,SALES,quote()),order)
        with self.assertRaises(Conflict):self.ledger.submit_order(rid(),SALES,quote())
    def test_two_native_processes_same_request_commit_once(self):
        key=rid();barrier=threading.Barrier(2)
        def submit():barrier.wait();return self.ledger.submit_order(key,SALES,quote())
        with ThreadPoolExecutor(2) as pool:values=list(pool.map(lambda _:submit(),range(2)))
        self.assertEqual(values[0],values[1]);self.assertEqual(self.ledger.inventory()['counts']['orders'],1)
    def test_concurrent_note_and_void_have_one_revision_winner(self):
        order=self.order();barrier=threading.Barrier(2)
        def call(note):
            barrier.wait()
            try:
                if note:self.ledger.append_note(rid(),SALES,order['order_id'],'说明',expected_revision=1)
                else:self.ledger.set_state(rid(),ADMIN,order['order_id'],'void','作废',expected_revision=1)
                return 'ok'
            except Conflict:return 'conflict'
        with ThreadPoolExecutor(2) as pool:values=list(pool.map(call,[True,False]))
        self.assertCountEqual(values,['ok','conflict']);self.assertEqual(self.ledger.inventory()['revision'],3)
    def test_concurrent_price_publication_preserves_cas(self):
        barrier=threading.Barrier(2)
        def call(version):
            barrier.wait()
            try:self.ledger.publish_prices(rid(),ADMIN,prices(version),expected_price_version_id='v1');return 'ok'
            except Conflict:return 'conflict'
        with ThreadPoolExecutor(2) as pool:values=list(pool.map(call,['v2','v3']))
        self.assertCountEqual(values,['ok','conflict']);self.assertEqual(self.ledger.inventory()['counts']['price_versions'],2)
    def test_process_exit_before_commit_and_after_first_line_roll_back(self):
        before=self.ledger.inventory()
        for phase in ['line_inserted','before_commit']:
            key=rid();self.ledger.test_fault=phase
            with self.assertRaises(UnknownCommit):self.ledger.submit_order(key,SALES,QuoteSnapshot('v1',(NormalLine('P','1'),NormalLine('P','2'))))
            self.ledger.test_fault=None
            self.assertIsNone(self.ledger.query_request(key,SALES));self.assertEqual(self.ledger.inventory(),before)
    def test_process_exit_after_commit_recovers_original_without_duplicate(self):
        key=rid();self.ledger.test_fault='after_commit'
        with self.assertRaises(UnknownCommit):self.ledger.submit_order(key,SALES,quote())
        self.ledger.test_fault=None;saved=self.ledger.query_request(key,SALES)
        self.assertIsNotNone(saved);self.assertEqual(self.ledger.submit_order(key,SALES,quote()),saved)
        self.assertEqual(self.ledger.inventory()['counts']['orders'],1)
    def test_native_role_and_owner_checks_do_not_trust_display_fields(self):
        order=self.order()
        with self.assertRaises(Forbidden):self.ledger.append_note(rid(),OTHER,order['order_id'],'跨用户',expected_revision=1)
        with self.assertRaises(Forbidden):self.ledger.set_state(rid(),SALES,order['order_id'],'void','原因',expected_revision=1)
        with self.assertRaises(Forbidden):self.ledger.publish_prices(rid(),SALES,prices('v2'))
        with self.assertRaises(Forbidden):self.ledger.query_request(order['request_id'],OTHER)
    def test_direct_python_financial_write_is_blocked_in_rust_adapter(self):
        with self.assertRaises(LedgerError):
            with self.ledger.connection():pass
    def test_money_above_js_integer_range_remains_exact_in_db_and_json(self):
        self.ledger.publish_prices(rid(),ADMIN,prices('v2','100000000'),expected_price_version_id='v1')
        result=self.ledger.submit_order(rid(),SALES,quote('v2','922337203.6854775807'))
        self.assertEqual(result['income_cents'],'9223372036854775807')
        self.assertEqual(self.ledger.inventory(),Ledger(self.ledger.path).inventory())
        before=self.ledger.inventory()
        with self.assertRaises(LedgerError):self.ledger.submit_order(rid(),SALES,quote('v2','922337203.6854775808'))
        self.assertEqual(self.ledger.inventory(),before)
    def test_schema_unknown_or_altered_is_rejected_without_overwriting(self):
        with sqlite3.connect(self.ledger.path) as c:c.execute('PRAGMA user_version=999')
        before=hashlib.sha256(self.ledger.path.read_bytes()).hexdigest()
        with self.assertRaises(InvalidDatabase):self.ledger.inventory()
        self.assertEqual(hashlib.sha256(self.ledger.path.read_bytes()).hexdigest(),before)
        with self.assertRaises(FileExistsError):RustLedger.create(self.ledger.path,BINARY,auxiliary=os.name!='nt')
    def test_binary_hash_failure_does_not_fall_back_to_python(self):
        self.ledger.expected_sha256='0'*64
        with self.assertRaises(InvalidDatabase):self.ledger.submit_order(rid(),SALES,quote())
        self.assertEqual(Ledger(self.ledger.path).inventory()['counts']['orders'],0)
    def test_native_online_snapshot_and_independent_python_restore_match(self):
        self.order();target=self.root/'native-backup.sqlite3';checked=self.ledger.backup_snapshot(target)
        self.assertEqual(checked,Ledger(target).inventory());self.assertEqual(checked,self.ledger.inventory())
        with self.assertRaises(FileExistsError):self.ledger.backup_snapshot(target)
        manager=Backups.create(self.root/'backups',auxiliary=os.name!='nt');entry=manager.create_backup(self.ledger)
        restored=restore_backup(manager.root/entry['backup_id'],self.root/'restored.sqlite3')
        self.assertEqual(restored.inventory(),self.ledger.inventory())
    def test_legacy_import_is_only_previewed_in_memory_and_rust_commits_atomically(self):
        raw=current_book(self.root/'source.xlsx').read_bytes();plan=preview_bytes(raw,'xlsx');owner=rid()
        result=apply_source(self.ledger,ADMIN,owner,raw,'xlsx',expected_review_sha256=plan.review_sha256)
        self.assertEqual(result['created_orders'],2)
        self.assertEqual(apply_source(self.ledger,ADMIN,owner,raw,'xlsx',expected_review_sha256=plan.review_sha256),result)
        self.assertEqual(self.ledger.inventory(),Ledger(self.ledger.path).inventory())
        with self.ledger.connection(readonly=True) as c:self.assertEqual(verify_provenance(c),1)
    def test_import_native_process_interruption_is_atomic_and_retry_safe(self):
        raw=current_book(self.root/'source.xlsx').read_bytes();plan=preview_bytes(raw,'xlsx');owner=rid();before=self.ledger.inventory()
        self.ledger.test_fault='import_line_inserted'
        with self.assertRaises(UnknownCommit):apply_source(self.ledger,ADMIN,owner,raw,'xlsx',expected_review_sha256=plan.review_sha256)
        self.ledger.test_fault=None;self.assertEqual(self.ledger.inventory(),before)
        self.ledger.test_fault='import_after_commit'
        with self.assertRaises(UnknownCommit):apply_source(self.ledger,ADMIN,owner,raw,'xlsx',expected_review_sha256=plan.review_sha256)
        self.ledger.test_fault=None
        saved=apply_source(self.ledger,ADMIN,owner,raw,'xlsx',expected_review_sha256=plan.review_sha256)
        self.assertEqual(saved['created_orders'],2);self.assertEqual(self.ledger.inventory()['counts']['orders'],2)

    def test_missing_worker_is_unavailable_without_an_implicit_financial_fallback(self):
        self.ledger.binary=self.root/'missing-worker.exe'
        with self.assertRaises(InvalidDatabase):self.ledger.submit_order(rid(),SALES,quote())
        self.assertEqual(Ledger(self.ledger.path).inventory()['counts']['orders'],0)
