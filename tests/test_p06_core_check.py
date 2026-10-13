"""Checks protecting shadow evidence, platform gating and Windows UTF-8 reads."""
import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import p06_core_check as check
import p06_cases
class P06CoreCheckTests(unittest.TestCase):
    def test_exact_comparison_rejects_numeric_type_changes_and_partial_rows(self):
        self.assertIsNotNone(check.first_difference({'cents':'9007199254740993'},{'cents':9007199254740993}))
        self.assertIsNotNone(check.first_difference([1,2],[1]))
        self.assertIsNone(check.first_difference({'x':[None,False,'1']},{'x':[None,False,'1']}))
    def test_golden_reads_same_asset_and_maps_historical_candidate_profile(self):
        items=[c for c in p06_cases.cases() if c[0]=='golden']
        self.assertEqual(len(items),53)
        self.assertEqual({c[2]['snapshot']['numeric_profile'] for c in items},{'numeric-v1'})
    def test_fingerprints_do_not_depend_on_windows_default_gbk(self):
        def forbidden(*args,**kwargs):raise AssertionError('text read without explicit UTF-8')
        with patch.object(Path,'read_text',side_effect=forbidden):
            self.assertIn('Cargo.lock',check.fingerprints())
    def test_windows_mode_blocks_before_rust_or_real_paths_on_other_os(self):
        with redirect_stdout(io.StringIO()),tempfile.TemporaryDirectory() as folder,patch.object(check,'new_output',return_value=Path(folder)),patch.object(check.platform,'system',return_value='Linux'),patch.object(check,'run',side_effect=AssertionError('Rust launched')):
            self.assertEqual(check.main(['--windows-smoke','--output',folder]),1)
            result=json.loads((Path(folder)/'report.json').read_text(encoding='utf-8'))
            self.assertEqual(result['failure']['reason'],'ACTUAL_WINDOWS_REQUIRED')
            self.assertFalse(result['production_paths_accessed'])
    def test_output_directory_never_overwrites_previous_or_accepts_outside_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):check.new_output(folder)
