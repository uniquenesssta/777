"""Native/auxiliary boundaries; no fabricated Windows backup evidence."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import p05_ledger_check as check

class LedgerCheckTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def report(self):return json.loads((self.root/'report.json').read_text(encoding='utf-8'))

    def test_non_windows_blocks_before_checks_and_native_directory_or_acl_access(self):
        with patch.object(check,'new_output',return_value=self.root),patch.object(check.platform,'system',return_value='auxiliary'),patch.object(check,'run_checks',side_effect=AssertionError('checks touched')),patch.object(check,'windows_smoke',side_effect=AssertionError('native touched')),patch('sys.stdout',new=io.StringIO()):
            self.assertEqual(check.main(['--windows-smoke','--output','ignored']),2)
        report=self.report();self.assertEqual(report['status'],'blocked');self.assertIsNone(report['native_smoke']);self.assertFalse(report['production_paths_accessed'])

    def test_failed_native_smoke_cannot_turn_successful_unit_checks_into_acceptance(self):
        with patch.object(check,'new_output',return_value=self.root),patch.object(check.platform,'system',return_value='Windows'),patch.object(check,'run_checks',return_value={'status':'passed'}),patch.object(check,'windows_smoke',side_effect=OSError('synthetic protection failure')),patch('sys.stdout',new=io.StringIO()):
            self.assertEqual(check.main(['--windows-smoke','--output','ignored']),2)
        report=self.report();self.assertEqual(report['status'],'failed');self.assertIn('synthetic protection failure',report['error']);self.assertEqual(report['P05_01_acceptance'],'pending')

    def test_checks_only_never_calls_native_smoke_or_claims_windows_environment_acceptance(self):
        with patch.object(check,'new_output',return_value=self.root),patch.object(check,'run_checks',return_value={'status':'passed'}),patch.object(check,'windows_smoke',side_effect=AssertionError('native touched')),patch('sys.stdout',new=io.StringIO()):
            self.assertEqual(check.main(['--checks-only','--output','ignored']),0)
        report=self.report();self.assertEqual(report['status'],'auxiliary_checks_passed_Windows_pending');self.assertIsNone(report['native_smoke']);self.assertFalse(report['existing_E_or_shared_directories_modified'])

    def test_existing_report_output_is_not_overwritten(self):
        marker=self.root/'keep.txt';marker.write_text('preserve')
        with patch.object(check,'new_output',side_effect=FileExistsError('already exists')),patch.object(check,'run_checks',side_effect=AssertionError('checks touched')),self.assertRaises(FileExistsError):check.main(['--checks-only','--output',str(self.root)])
        self.assertEqual(marker.read_text(),'preserve')

if __name__=='__main__':unittest.main()
