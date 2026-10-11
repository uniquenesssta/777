"""CLI boundaries: read-only explicit lookup and Windows gate."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import p03_file_check as check
from quote_files.configuration import save_config
from quote_files.transactions import digest


class P03DiagnosticTests(unittest.TestCase):
    def test_nonwindows_smoke_is_blocked_without_gui_or_transaction(self):
        with patch.object(check.platform, 'system', return_value='Linux'), patch.object(check.baseline_check, 'emit') as emit, patch.object(check.gui, 'run_pair', side_effect=AssertionError('GUI called')):
            self.assertEqual(check.main(['--windows-smoke']), 2)
            self.assertEqual(emit.call_args.args[0]['status'], 'blocked')
            self.assertFalse(emit.call_args.args[0]['production_paths_accessed'])

    def test_explicit_config_status_is_readonly_and_uses_recorded_hash(self):
        with tempfile.TemporaryDirectory(prefix='777-p03-diagnostic-') as folder:
            path = Path(folder) / 'synthetic.json'
            path.write_bytes(b'{"value":1}')
            _, req = save_config(path, b'{"value":2}', expected_hash=digest(path.read_bytes()), validator=json.loads)
            before = check.gui.files(Path(folder))
            with patch.object(check.baseline_check, 'emit') as emit:
                self.assertEqual(check.main(['--request-status', str(path), '--request-id', req.request_id]), 0)
                self.assertEqual(emit.call_args.args[0]['request']['status'], 'committed')
            self.assertEqual(check.gui.files(Path(folder)), before)

    def test_lookup_output_cannot_overwrite_original_and_requires_id(self):
        with patch.object(check.sys, 'stderr'):
            with self.assertRaises(SystemExit):
                check.main(['--request-status', 'source.xlsx'])
            with self.assertRaises(SystemExit):
                check.main(['--request-status', 'source.xlsx', '--request-id', str(uuid.uuid4()), '--output', 'source.xlsx'])


if __name__ == '__main__':
    unittest.main()
