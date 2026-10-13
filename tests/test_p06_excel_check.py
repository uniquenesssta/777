import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import p06_excel_check as check
class P06ExcelCheckTests(unittest.TestCase):
    def test_non_windows_refuses_before_native_commands(self):
        with tempfile.TemporaryDirectory() as folder,redirect_stdout(io.StringIO()),patch.object(check,'new_output',return_value=Path(folder)),patch.object(check.platform,'system',return_value='Linux'),patch.object(check,'run',side_effect=AssertionError('native started')):
            self.assertEqual(check.main(['--windows-smoke','--output',folder]),1)
            report=json.loads((Path(folder)/'report.json').read_text(encoding='utf-8'));self.assertEqual(report['failure']['reason'],'ACTUAL_WINDOWS_REQUIRED')
    def test_original_reports_and_data_directories_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):check.new_output(folder)
    def test_fingerprints_use_bytes_and_cover_format_paths_and_cli(self):
        with patch.object(Path,'read_text',side_effect=AssertionError('default decoder')):
            fingerprints=check.fingerprints()
            for file in ['crates/quote-excel/src/read.rs','crates/quote-excel/src/write.rs','quote_files/native_excel.py','tools/p05_import.py','tests/legacy_worker_fixture.py','docs/verification/P06-03-dependencies.json']:self.assertIn(file,fingerprints)
    def test_native_smoke_does_not_accept_simulated_platform_identity(self):
        with patch.object(check.platform,'system',return_value='Linux'):
            with self.assertRaisesRegex(RuntimeError,'ACTUAL_WINDOWS_REQUIRED'):check.windows_smoke()
