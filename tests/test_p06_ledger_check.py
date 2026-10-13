import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import p06_ledger_check as check
class P06LedgerCheckTests(unittest.TestCase):
    def test_windows_mode_refuses_auxiliary_platform_before_native_execution(self):
        with tempfile.TemporaryDirectory() as folder,redirect_stdout(io.StringIO()),patch.object(check,'new_output',return_value=Path(folder)),patch.object(check.os,'name','posix'),patch.object(check,'run',side_effect=AssertionError('native started')):
            self.assertEqual(check.main(['--windows-smoke','--output',folder]),1)
            r=json.loads((Path(folder)/'report.json').read_text(encoding='utf-8'));self.assertEqual(r['failure']['reason'],'ACTUAL_WINDOWS_REQUIRED')
    def test_source_fingerprints_are_bytes_based_without_default_gbk_reads(self):
        with patch.object(Path,'read_text',side_effect=AssertionError('default decoder')):
            fp=check.fingerprints();self.assertIn('quote_service/rust_ledger.py',fp);self.assertIn('crates/quote-ledger/src/store.rs',fp)
    def test_report_output_cannot_adopt_an_existing_or_real_data_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):check.new_output(folder)
    def test_windows_smoke_cannot_be_run_as_a_platform_simulation(self):
        with patch.object(check.os,'name','posix'):
            with self.assertRaisesRegex(RuntimeError,'ACTUAL_WINDOWS_REQUIRED'):check.windows_smoke()
