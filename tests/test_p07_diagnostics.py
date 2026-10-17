import importlib.util
import json
import logging
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import p07_diagnostics as diagnostics

class DiagnosticsTests(unittest.TestCase):
    def test_flood_redaction_os_errors_and_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = logging.Logger('diagnostics-test')
            from logging.handlers import RotatingFileHandler
            handler = RotatingFileHandler(Path(tmp) / 'development.jsonl', maxBytes=1024, backupCount=4, encoding='utf-8')
            logger.addHandler(handler)
            with patch.object(diagnostics, '_LOGGER', logger), patch.object(diagnostics, '_RECENT', {}):
                for _ in range(10000):
                    diagnostics.event('poll.failed', code='PATH_UNAVAILABLE')
                diagnostics.failure('configure', PermissionError(13, 'Access denied', r'\\server\共享\backup'))
                diagnostics.failure('package', RuntimeError('password=VERY_SECRET token=SECRET'))
                diagnostics.event('runtime.stop')
                handler.flush()
                rows=[json.loads(s) for s in (Path(tmp)/'development.jsonl').read_text(encoding='utf-8').splitlines()]
                self.assertLessEqual(len(rows), 5)
                self.assertTrue(any(r['fields'].get('suppressed') == 9999 for r in rows))
                raw=(Path(tmp)/'development.jsonl').read_text(encoding='utf-8')
                self.assertNotIn('VERY_SECRET', raw)
                self.assertIn('Access denied', raw)
                for i in range(300): diagnostics.event('different', sequence=i)
                self.assertEqual(len(list(Path(tmp).glob('development.jsonl*'))), 5)
                self.assertTrue(all(p.stat().st_size <= 1024 for p in Path(tmp).iterdir()))
            handler.close()

    def test_control_poll_does_not_log_payload(self):
        from p07_developer import Developer
        owner=object.__new__(Developer)
        owner._handle=lambda data: {'password':'NEVER_LOG_ME'}
        with patch('p07_developer.diagnostics.event') as log:
            owner.handle({'op':'status'})
            log.assert_not_called()
            owner.handle({'op':'bootstrap'})
            log.assert_not_called()
            owner.handle({'op':'select','password':'NEVER_LOG_ME'})
            self.assertEqual(log.call_count, 2)
            self.assertNotIn('NEVER_LOG_ME', str(log.call_args_list))
