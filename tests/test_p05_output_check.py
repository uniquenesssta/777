"""Native gating and honest persisted failure/output evidence."""
import json
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'tools')]
import p05_output_check as tool


class OutputCheckTests(unittest.TestCase):
    def run_tool(self,mode,checks=None,native=None,system='Windows'):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'reports/result'
            from p01_validation import new_output
            with patch.object(tool,'new_output',side_effect=lambda path:new_output(path,root=root)),patch('sys.stdout',new=io.StringIO()),patch.object(tool.platform,'system',return_value=system),patch.object(tool,'run_checks',return_value=checks or {'status':'passed','tests_run':1}),patch.object(tool,'windows_smoke',side_effect=native or (lambda:{'status':'passed'})):
                result=tool.main([mode,'--output',str(p)])
            return result,json.loads((p/'report.json').read_text())
    def test_non_windows_blocks_before_any_checks_or_native_access(self):
        def forbidden():raise AssertionError('native called')
        code,report=self.run_tool('--windows-smoke',native=forbidden,system='Linux')
        self.assertEqual(code,1);self.assertIsNone(report['checks']);self.assertIsNone(report['native_smoke'])
    def test_checks_failure_retained_and_never_launches_native(self):
        code,report=self.run_tool('--windows-smoke',checks={'status':'failed','tests_run':1,'failures':1})
        self.assertEqual(code,1);self.assertEqual(report['status'],'failed_checks');self.assertIsNone(report['native_smoke'])
    def test_native_exception_preserves_full_traceback_and_pending_acceptance(self):
        def failed():raise OSError('isolated native error')
        code,report=self.run_tool('--windows-smoke',native=failed)
        self.assertEqual(code,1);self.assertIn('OSError',report['native_error']['traceback']);self.assertEqual(report['Windows_acceptance'],'pending')
    def test_auxiliary_success_cannot_claim_native_or_acceptance(self):
        def forbidden():raise AssertionError('native called')
        code,report=self.run_tool('--checks-only',native=forbidden,system='Linux')
        self.assertEqual(code,0);self.assertIsNone(report['native_smoke']);self.assertEqual(report['Windows_acceptance'],'pending')
    def test_existing_output_is_refused_and_original_content_kept(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'reports/existing';p.mkdir(parents=True);marker=p/'report.json';marker.write_text('original')
            from p01_validation import new_output
            with patch.object(tool,'new_output',side_effect=lambda path:new_output(path,root=root)),self.assertRaises(FileExistsError):tool.main(['--checks-only','--output',str(p)])
            self.assertEqual(marker.read_text(),'original')
