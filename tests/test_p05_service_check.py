"""Native service collector never substitutes mocked/auxiliary evidence for Windows."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'tools')]
import p05_service_check as check


class ServiceCheckTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def report(self):return json.loads((self.root/'report.json').read_text(encoding='utf-8'))
    def test_off_windows_blocks_before_service_or_gui_or_dpapi_access(self):
        with patch.object(check,'new_output',return_value=self.root),patch.object(check.platform,'system',return_value='auxiliary'),patch.object(check,'run_checks',side_effect=AssertionError('checks reached')),patch.object(check,'windows_smoke',side_effect=AssertionError('native reached')),patch('sys.stdout',new=io.StringIO()):
            self.assertEqual(check.main(['--windows-smoke','--output','ignored']),2)
        self.assertEqual(self.report()['status'],'blocked');self.assertIsNone(self.report()['native_smoke'])
    def test_missing_dependencies_are_visible_and_do_not_run_checks(self):
        with patch.object(check,'new_output',return_value=self.root),patch.object(check,'dependencies',return_value=[{'status':'mismatch_or_missing'}]),patch.object(check,'run_checks',side_effect=AssertionError('checks reached')),patch('sys.stdout',new=io.StringIO()):
            self.assertEqual(check.main(['--checks-only','--output','ignored']),2)
        self.assertIn('requirements-service.txt',self.report()['reason'])
    def test_failed_native_step_keeps_full_exception_and_pending_acceptance(self):
        output=io.StringIO()
        with patch.object(check,'new_output',return_value=self.root),patch.object(check.platform,'system',return_value='Windows'),patch.object(check,'dependencies',return_value=[]),patch.object(check,'run_checks',return_value={'status':'passed','tests_run':1,'failures':0,'errors':0,'failure_details':[]}),patch.object(check,'windows_smoke',side_effect=RuntimeError('synthetic native failure')),patch('sys.stdout',new=output):
            self.assertEqual(check.main(['--windows-smoke','--output','ignored']),2)
        self.assertEqual(self.report()['P05_02_acceptance'],'pending');self.assertIn('synthetic native failure',self.report()['native_error_traceback']);self.assertIn('synthetic native failure',json.loads(output.getvalue())['error'])
    def test_existing_output_and_auxiliary_mode_cannot_replace_native_results(self):
        with patch.object(check,'new_output',side_effect=FileExistsError('preserve')),self.assertRaises(FileExistsError):check.main(['--checks-only','--output','ignored'])
        with patch.object(check,'new_output',return_value=self.root),patch.object(check,'dependencies',return_value=[]),patch.object(check,'run_checks',return_value={'status':'passed','tests_run':1,'failures':0,'errors':0,'failure_details':[]}),patch.object(check,'windows_smoke',side_effect=AssertionError('native reached')),patch('sys.stdout',new=io.StringIO()):
            self.assertEqual(check.main(['--checks-only','--output','ignored']),0)
        self.assertEqual(self.report()['status'],'auxiliary_service_checks_passed_Windows_pending');self.assertIsNone(self.report()['native_smoke'])


if __name__=='__main__':unittest.main()
