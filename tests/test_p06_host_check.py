import importlib.util,json,os,tempfile,unittest,io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('p06_host_tool',ROOT/'tools/p06_host_check.py');tool=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(tool)
class P06HostCheckTests(unittest.TestCase):
    def test_simulated_platform_never_enters_native_windows_gui(self):
        with patch.object(tool.platform,'system',return_value='Linux'),self.assertRaisesRegex(RuntimeError,'ACTUAL_WINDOWS_REQUIRED'):tool.windows_smoke()
    def test_windows_mode_refuses_before_native_commands_and_records_failure(self):
        with tempfile.TemporaryDirectory() as tmp,redirect_stdout(io.StringIO()),patch.object(tool,'new_output',return_value=Path(tmp)),patch.object(tool.platform,'system',return_value='Linux'),patch.object(tool,'run',side_effect=AssertionError('native commands reached')):
            out=Path(tmp)/'new';self.assertEqual(tool.main(['--windows-smoke','--output',str(out)]),1);r=json.loads((Path(tmp)/'report.json').read_bytes());self.assertIn('ACTUAL_WINDOWS_REQUIRED',r['failure']);self.assertEqual(r['commands'],[])
    def test_report_cannot_overwrite_existing_evidence_or_real_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);(out/'report.json').write_text('original')
            with self.assertRaises(Exception):tool.main(['--checks-only','--output',str(out)])
            self.assertEqual((out/'report.json').read_text(),'original')
    def test_native_resources_casefold_schema_and_old_gui_source_are_fingerprinted(self):
        f=tool.fingerprints()
        for p in ['crates/quote-host/src/host.rs','crates/quote-host/src/casefold-v15.json','docs/verification/P06-04-auth-schema.sql','quote_service/native_host.py','tools/p05_service_check.py','.github/workflows/p06-windows.yml']:
            self.assertIn(p,f);self.assertEqual(len(f[p]),64)
