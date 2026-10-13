"""CLI uses actual account validation, owner lock, backup gate and source SHA."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import p05_import as entry
from quote_service.hosting import initialize, load
from quote_files.transactions import file_lock
from quote_import import preview_bytes
from import_fixture import current_book


class ImportEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='777-import-cli-')
        self.root = Path(self.temp.name)
        self.secret = 'isolated-import-password'
        initialize(self.root / 'host', self.root / 'backup', 'manager', self.secret, hosts=['localhost'], auxiliary=os.name != 'nt')
        _, _, self.service = load(self.root / 'host', auxiliary=os.name != 'nt')
        token = self.service.auth.login('manager', self.secret, 'fixture')['token']
        admin = self.service.auth.authenticate(token)
        self.service.auth.create_account(admin, 'sales-one', self.secret, 'sales')
        self.service.auth.logout(token)
        self.source = current_book(self.root / 'source.xlsx')
        self.plan = preview_bytes(self.source.read_bytes(), 'xlsx')
        self.output = self.root / 'output';self.output.mkdir()

    def tearDown(self):self.temp.cleanup()

    def arguments(self, **changes):
        args = {'--source': str(self.source), '--review-sha256': self.plan.review_sha256,
                '--host-root': str(self.root / 'host'), '--username': 'manager', '--owner': 'sales-one', '--output': 'ignored'}
        args.update(changes)
        return ['apply', *[v for pair in args.items() for v in pair]]

    def command(self, args, *, save_failure=False):
        original_load = load
        def native_independent_load(root, **kw):
            return original_load(root, auxiliary=os.name != 'nt', **kw)
        stdout = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(entry.platform, 'system', return_value='Windows'))
            stack.enter_context(patch.object(entry, 'new_output', return_value=self.output))
            stack.enter_context(patch.object(entry, 'load', side_effect=native_independent_load))
            stack.enter_context(patch.object(entry.getpass, 'getpass', return_value=self.secret))
            stack.enter_context(patch('sys.stdout', new=stdout))
            if save_failure:stack.enter_context(patch.object(Path, 'write_text', side_effect=OSError('report disk failure')))
            code = entry.main(args)
        report = json.loads((self.output / 'report.json').read_text(encoding='utf-8')) if (self.output / 'report.json').exists() else None
        return code, report, stdout.getvalue()

    def test_off_windows_blocks_before_source_or_output_access(self):
        with patch.object(entry.platform, 'system', return_value='auxiliary'), patch.object(entry, 'read_source', side_effect=AssertionError('source reached')), patch.object(entry, 'new_output', side_effect=AssertionError('output reached')), patch('sys.stdout', new=io.StringIO()):
            self.assertEqual(entry.main(['preview', '--source', 'x.xlsx', '--output', 'ignored']), 2)

    def test_real_login_owner_and_complete_backup_gate_import(self):
        code, report, text = self.command(self.arguments())
        self.assertEqual(code, 0, text)
        self.assertEqual(report['status'], 'committed')
        self.assertTrue(report['complete_pre_import_backup'])
        self.assertEqual(self.service.ledger.inventory()['counts']['orders'], 2)
        self.assertNotIn(self.secret, text)
        self.assertNotIn('同秒客户', text)
        with self.service.auth.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM sessions').fetchone()[0], 0)

    def test_actual_sales_login_is_denied_before_backup_or_ledger_write(self):
        before = self.service.ledger.inventory()
        with patch('quote_service.app.Service.backup', side_effect=AssertionError('backup reached')):
            code, report, _ = self.command(self.arguments(**{'--username': 'sales-one'}))
        self.assertEqual(code, 2)
        self.assertEqual(report['error_type'], 'Forbidden')
        self.assertEqual(self.service.ledger.inventory(), before)

    def test_owner_must_exist_and_be_enabled(self):
        before = self.service.ledger.inventory()
        code, report, _ = self.command(self.arguments(**{'--owner': 'no-account'}))
        self.assertEqual(code, 2)
        self.assertEqual(self.service.ledger.inventory(), before)
        self.assertIn('现有账户', report['reason'])

    def test_running_host_owner_lock_refuses_cli_before_import(self):
        before = self.service.ledger.inventory()
        with file_lock(self.root / 'host/service-owner'):
            code, report, _ = self.command(self.arguments())
        self.assertEqual(code, 2)
        self.assertEqual(report['error_type'], 'FileBusy')
        self.assertEqual(self.service.ledger.inventory(), before)

    def test_failed_complete_backup_keeps_ledger_unchanged(self):
        before = self.service.ledger.inventory()
        with patch('quote_service.app.Service.backup', side_effect=OSError('backup unavailable')):
            code, report, _ = self.command(self.arguments())
        self.assertEqual(code, 2)
        self.assertEqual(self.service.ledger.inventory(), before)

    def test_changed_review_hash_does_not_open_host_or_ask_password(self):
        with patch.object(entry, 'load', side_effect=AssertionError('host reached')):
            # command helper normally patches load; use the direct entry here.
            with patch.object(entry.platform, 'system', return_value='Windows'), patch.object(entry, 'new_output', return_value=self.output), patch.object(entry.getpass, 'getpass', side_effect=AssertionError('password reached')), patch('sys.stdout', new=io.StringIO()):
                self.assertEqual(entry.main(self.arguments(**{'--review-sha256': '0' * 64})), 2)
        self.assertEqual(self.service.ledger.inventory()['counts']['orders'], 0)

    def test_report_failure_cannot_disguise_a_committed_batch(self):
        code, report, stdout = self.command(self.arguments(), save_failure=True)
        self.assertEqual(code, 0, stdout)
        self.assertIsNone(report)
        self.assertIn('"status": "committed"', stdout)
        self.assertIn('"request_id"', stdout)
        self.assertIn('报告保存失败', stdout)
        self.assertEqual(self.service.ledger.inventory()['counts']['import_batches'], 1)

    def test_preview_report_failure_never_claims_a_completed_import(self):
        code, report, stdout = self.command(['preview', '--source', str(self.source), '--output', 'ignored'], save_failure=True)
        self.assertEqual(code, 2, stdout)
        self.assertIsNone(report)
        self.assertIn('本次未完成导入', stdout)
        self.assertNotIn('导入已提交', stdout)
        self.assertEqual(self.service.ledger.inventory()['counts']['orders'], 0)


if __name__ == '__main__':unittest.main()
