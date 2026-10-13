"""Native evidence cannot be fabricated by auxiliary mode or failure."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import p05_import_check as check
from p01_validation import new_output


class ImportCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.root = Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def report(self):return json.loads((self.root / 'report.json').read_text(encoding='utf-8'))

    def test_off_windows_blocks_before_checks_or_native_access(self):
        with patch.object(check, 'new_output', return_value=self.root), patch.object(check.platform, 'system', return_value='auxiliary'), patch.object(check, 'run_checks', side_effect=AssertionError('checks reached')), patch.object(check, 'windows_smoke', side_effect=AssertionError('native reached')), patch('sys.stdout', new=io.StringIO()):
            self.assertEqual(check.main(['--windows-smoke', '--output', 'ignored']), 2)
        self.assertEqual(self.report()['status'], 'blocked')
        self.assertIsNone(self.report()['native_smoke'])

    def test_failed_native_step_preserves_traceback_and_pending_acceptance(self):
        stdout = io.StringIO()
        with patch.object(check, 'new_output', return_value=self.root), patch.object(check.platform, 'system', return_value='Windows'), patch.object(check, 'run_checks', return_value={'status': 'passed', 'tests_run': 1, 'failures': 0, 'errors': 0, 'skipped': [], 'failure_details': []}), patch.object(check, 'windows_smoke', side_effect=RuntimeError('synthetic native error')), patch('sys.stdout', new=stdout):
            self.assertEqual(check.main(['--windows-smoke', '--output', 'ignored']), 2)
        self.assertIn('synthetic native error', self.report()['native_error_traceback'])
        self.assertEqual(self.report()['Windows_acceptance'], 'pending')
        self.assertIn('synthetic native error', json.loads(stdout.getvalue())['error'])

    def test_auxiliary_mode_never_runs_native_and_old_report_is_not_overwritten(self):
        with patch.object(check, 'new_output', return_value=self.root), patch.object(check, 'run_checks', return_value={'status': 'passed', 'tests_run': 1, 'failures': 0, 'errors': 0, 'skipped': [], 'failure_details': []}), patch.object(check, 'windows_smoke', side_effect=AssertionError('native reached')), patch('sys.stdout', new=io.StringIO()):
            self.assertEqual(check.main(['--checks-only', '--output', 'ignored']), 0)
        self.assertEqual(self.report()['status'], 'auxiliary_import_checks_passed_Windows_pending')
        with patch.object(check, 'new_output', side_effect=FileExistsError('old report')), self.assertRaises(FileExistsError):
            check.main(['--checks-only', '--output', 'ignored'])

    def test_failed_checks_are_visible_and_do_not_launch_native(self):
        stdout = io.StringIO()
        failed = {'status': 'failed', 'tests_run': 1, 'failures': 0, 'errors': 1, 'skipped': [], 'failure_details': [{'test_id': 'synthetic', 'error': 'fixture failed'}]}
        with patch.object(check, 'new_output', return_value=self.root), patch.object(check.platform, 'system', return_value='Windows'), patch.object(check, 'run_checks', return_value=failed), patch.object(check, 'windows_smoke', side_effect=AssertionError('native reached')), patch('sys.stdout', new=stdout):
            self.assertEqual(check.main(['--windows-smoke', '--output', 'ignored']), 2)
        self.assertEqual(json.loads(stdout.getvalue())['checks']['failure_details'], failed['failure_details'])

    def test_real_report_output_policy_requires_new_child(self):
        out = new_output(self.root / 'reports/result', root=self.root)
        with self.assertRaises(FileExistsError):new_output(out, root=self.root)
        with self.assertRaises(ValueError):new_output(self.root / 'outside', root=self.root)


if __name__ == '__main__':unittest.main()
