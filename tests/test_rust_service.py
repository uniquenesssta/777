"""Unmodified Python client protocol over actual pinned HTTPS to native Rust ledger."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from quote_service.hosting import initialize,load
from quote_service.backend import select_backend
from quote_service.rust_ledger import RUST_FILES,file_hash
from quote_service.recovery import restore,manifest
from quote_service.protocol import APIError
from quote_ledger.backup import read_json
from quote_core import NormalLine,QuoteSnapshot,DraftDetails
from quote_service.journal import MemoryJournal
from quote_files.transactions import file_lock
from rust_service_fixture import Hosted,BINARY,ROOT
import test_service_boundary as original

class RustHTTPS(original.ServiceBoundaryTests):
    @classmethod
    def setUpClass(cls):cls.host=Hosted()
    def test_calculation_submission_and_listing_never_call_python_calculator(self):
        q=QuoteSnapshot('fixture-v1',(NormalLine('单件','4'),))
        with patch('quote_service.app.calculate_quote',side_effect=AssertionError('Python calculator called')):
            r=self.sales.request('POST','/v1/calculate',{'snapshot':{'price_version_id':'fixture-v1','lines':[{'line_kind':'normal','product_id':'单件','q':'4'}]}})
            self.assertEqual(r['totals']['income_cents'],'4000')
            order=self.sales.submit(q,DraftDetails('0001','00002','微信'),MemoryJournal())
            self.assertEqual(self.sales.request('GET','/v1/orders/'+order['order_id'])['income_cents'],'4000')
        self.assertEqual(self.host.service.ledger.backend,'rust')
    def test_native_commit_unknown_202_recovers_receipt_after_process_exit(self):
        from quote_service.client import CommitUnknown
        journal=MemoryJournal();q=QuoteSnapshot('fixture-v1',(NormalLine('单件','1'),))
        self.host.service.ledger.test_fault='after_commit'
        try:
            with self.assertRaises(CommitUnknown):self.sales.submit(q,DraftDetails(),journal)
        finally:self.host.service.ledger.test_fault=None
        self.assertIsNotNone(self.sales.check_pending(journal)['result']);self.assertIsNone(journal.read())
    def test_complete_v3_restore_preserves_worker_ledger_identity_and_maintenance(self):
        order=self.sales.submit(QuoteSnapshot('fixture-v1',(NormalLine('单件','2'),)),DraftDetails(),MemoryJournal())
        before=self.host.service.ledger.inventory();entry=self.host.service.backup(kind='maintenance')
        value=manifest(entry['service_bundle'],auxiliary=os.name!='nt')
        self.assertEqual(value['format'],'777-service-bundle-v3');self.assertTrue(RUST_FILES<=value['files'].keys())
        target=self.host.root/'native-restored'
        ledger,auth=restore(entry['service_bundle'],target,'manager','restored-password-123',auxiliary=os.name!='nt')
        self.assertEqual(ledger.backend,'rust');self.assertEqual(ledger.inventory(),before)
        self.assertEqual(ledger.query_request(order['request_id'],self.host.admin)['order_id'],order['order_id'])
        self.assertEqual(file_hash(target/'private/rust-ledger-worker.exe'),file_hash(BINARY))
        with self.assertRaises(APIError):auth.authenticate(self.sales.token)
        with self.assertRaises(APIError) as caught:load(target,auxiliary=os.name!='nt')
        self.assertEqual(caught.exception.code,'RECOVERY_MAINTENANCE_REQUIRED')

class BackendSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        initialize(self.root/'host',self.root/'backups','manager','fixture-password-123',hosts=['localhost'],auxiliary=os.name!='nt')
    def tearDown(self):self.temp.cleanup()
    def select(self,backend='rust',**kwargs):return select_backend(self.root/'host','manager','fixture-password-123',backend,binary=BINARY,notices=ROOT/'THIRD_PARTY_NOTICES.md',auxiliary=os.name!='nt',**kwargs)
    def config(self):return read_json(self.root/'host/private/service.json')
    def test_backend_migration_is_explicit_reversible_and_single_selected_writer(self):
        self.assertNotIn('ledger_backend',self.config());self.select();self.assertEqual(self.config()['ledger_backend'],'rust')
        _,_,service=load(self.root/'host',auxiliary=os.name!='nt');before=service.ledger.inventory()
        self.assertEqual(service.ledger.backend,'rust');self.select('python')
        _,_,service=load(self.root/'host',auxiliary=os.name!='nt');self.assertFalse(hasattr(service.ledger,'backend'));self.assertEqual(service.ledger.inventory(),before)
        self.select();_,_,service=load(self.root/'host',auxiliary=os.name!='nt');self.assertEqual(service.ledger.backend,'rust')
    def test_prepublication_process_failure_preserves_old_selection_and_database(self):
        before=self.config()
        def fail(phase):
            if phase=='before_publish':raise OSError('interrupted copy migration')
        with self.assertRaises(OSError):self.select(fault=fail)
        self.assertEqual(self.config(),before);self.assertTrue(all(not (self.root/'host/private'/f).exists() for f in RUST_FILES))
        self.select();self.assertEqual(self.config()['ledger_backend'],'rust')
    def test_after_publication_unknown_outcome_is_read_back_and_retry_does_not_duplicate(self):
        def fail(phase):
            if phase=='after_publish':raise OSError('lost migration result')
        with self.assertRaises(OSError):self.select(fault=fail)
        self.assertEqual(self.config()['ledger_backend'],'rust');first=self.config();self.assertEqual(self.select(),first)
        self.assertTrue(all((self.root/'host/private'/f).exists() for f in RUST_FILES))
    def test_live_owner_lock_blocks_migration_before_config_changes(self):
        from quote_files.transactions import FileBusy
        with file_lock(self.root/'host/service-owner'):
            with self.assertRaises(FileBusy):self.select()
        self.assertNotIn('ledger_backend',self.config())
    def test_unknown_native_resource_is_not_adopted_or_overwritten(self):
        target=self.root/'host/private/rust-ledger-worker.exe';target.write_bytes(b'unknown')
        with self.assertRaises(APIError):self.select()
        self.assertEqual(target.read_bytes(),b'unknown');self.assertNotIn('ledger_backend',self.config())
    def test_no_implicit_python_fallback_when_registered_worker_is_corrupt(self):
        self.select();path=self.root/'host/private/rust-ledger-worker.exe';path.write_bytes(path.read_bytes()+b'changed')
        from quote_ledger.paths import InvalidDatabase
        with self.assertRaises(InvalidDatabase):load(self.root/'host',auxiliary=os.name!='nt')

import test_service_query as query_reference
import test_service_outputs as output_reference
from rust_service_fixture import initialize_rust
class RustQueries(query_reference.QueryTests):
    def setUp(self):
        with patch.object(query_reference,'initialize',initialize_rust):super().setUp()

class RustOutputs(unittest.TestCase):
    def setUp(self):
        with patch.object(output_reference,'initialize',initialize_rust):output_reference.OutputTests.setUp(self)
    tearDown=output_reference.OutputTests.tearDown
    request=output_reference.OutputTests.request
    configure=output_reference.OutputTests.configure
    workbook=output_reference.OutputTests.workbook
    test_native_output_financial_revision_unchanged=output_reference.OutputTests.test_output_enqueue_and_duplicate_do_not_write_financial_ledger
    test_native_quote_workbook_exact_and_filtered=output_reference.OutputTests.test_public_workbook_is_exact_role_filtered_and_formula_free
    test_native_private_cost_output_boundary=output_reference.OutputTests.test_admin_public_report_also_excludes_cost_but_internal_stays_private
    test_native_price_changes_keep_original_output=output_reference.OutputTests.test_later_note_state_and_price_do_not_rewrite_original_output_snapshot
    test_native_output_error_keeps_order_and_original_sha=output_reference.OutputTests.test_excel_permission_failure_retry_never_books_or_changes_original_order
    test_native_png_frozen_payload=output_reference.OutputTests.test_png_is_based_on_saved_order_and_has_payload_metadata
    def test_v3_restore_keeps_output_queue_files_receipts_and_backend(self):
        self.configure();done=self.request();self.outputs.run_one(self.service);queued=self.request('excel_admin',self.actor)
        before=self.service.ledger.inventory();entry=self.service.backup(kind='maintenance')
        value=manifest(entry['service_bundle'],auxiliary=os.name!='nt');self.assertEqual(value['format'],'777-service-bundle-v3')
        target=self.root/'restore';restore(entry['service_bundle'],target,'manager','new-fixture-password',auxiliary=os.name!='nt')
        _,config,reopened=load(target,auxiliary=os.name!='nt',allow_maintenance=True)
        self.assertTrue(config['maintenance']);self.assertEqual(reopened.ledger.backend,'rust');self.assertEqual(reopened.ledger.inventory(),before)
        self.assertEqual(reopened.outputs.content(self.actor,done['job_id']),self.outputs.content(self.actor,done['job_id']))
        self.assertEqual(reopened.outputs.status(self.actor,queued['job_id'])['state'],'queued')
        self.assertEqual(reopened.outputs.receipt(self.actor,done['request_id'])['job_id'],done['job_id'])
