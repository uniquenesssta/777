"""Failure summaries retain the reported cause without compiler progress flooding."""
import json
import logging
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import p07_diagnostics as diagnostics
from p08_automatic.build_diagnostics import BuildDiagnostics


class BuildDiagnosticsTests(unittest.TestCase):
    def test_reported_failure_reaches_the_existing_runtime_file_and_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            logger = logging.Logger('package-diagnostics-test')
            handler = diagnostics.SessionFileHandler(Path(temp))
            logger.addHandler(handler)
            with patch.object(diagnostics, '_LOGGER', logger), patch.object(diagnostics, '_RECENT', {}):
                output = BuildDiagnostics('fixture-package')
                for _ in range(10000):
                    output.feed('QUOTE777_BUILD_STAGE=compile')
                    output.feed('   Compiling dependency v1.0.0')
                    output.feed('[MODULE_LEVEL_DIRECTIVE] use client warning')
                output.feed('error: failed to run custom build command for `quote-desktop`')
                output.feed("thread 'main' (40684) panicked at desktop\\src-tauri\\build.rs:49:10:")
                output.feed(r"Tauri desktop build configuration: resource path `/Users\name\stage\node-run.ps1` doesn't exist")
                output.feed('TAURI_BUILD_FAILED: 1')
                output.finish('failed')
            raw=(Path(temp)/'runtime.jsonl').read_text(encoding='utf8')
            rows=[json.loads(line) for line in raw.splitlines()]
            self.assertEqual(len(rows),2)
            self.assertIn('node-run.ps1',raw);self.assertIn('build.rs:49:10',raw)
            self.assertNotIn('Compiling dependency',raw)
            self.assertEqual(rows[-1]['fields']['stage'],'compile')
            self.assertLess(len(raw.encode()),16384)
            handler.close()

    def test_sensitive_lines_are_omitted_and_earlier_error_survives_progress(self):
        output=BuildDiagnostics('fixture')
        output.feed('error[E0432]: unresolved import `module`')
        for _ in range(10000):output.feed(' Compiling more output')
        output.feed('error: password=NEVER_KEEP')
        output.feed('error: https://user:NEVER_KEEP@example.test/file')
        output.feed('error: -----BEGIN PRIVATE KEY-----')
        for i in range(1000):output.feed('error: unique failure '+str(i))
        self.assertEqual(len(output.entries),8)
        self.assertGreater(output.omitted,0)
        self.assertIn('E0432',output.entries[0])
        self.assertNotIn('NEVER_KEEP',json.dumps(output.entries))
        output.feed('PACKAGE_RESUME_CONFLICT')
        self.assertEqual(output.code,'PACKAGE_RESUME_CONFLICT')

    def test_success_without_diagnostics_does_not_append_an_error_summary(self):
        with patch.object(diagnostics,'event') as event:
            BuildDiagnostics('fixture').finish('succeeded')
            event.assert_not_called()


if __name__=='__main__':unittest.main()
