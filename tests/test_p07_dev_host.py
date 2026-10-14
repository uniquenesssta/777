"""Development initialization must commit and release SQLite before host startup."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
import p07_dev_host as dev
from quote_service.auth import Auth


class DevelopmentDatabaseTests(unittest.TestCase):
    def run_prepare(self, *, reject_update=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            release = root / 'target/release'
            release.mkdir(parents=True)
            extension = '.exe' if os.name == 'nt' else ''
            for name in ['quote-host', 'quote-ledger']:
                (release / (name + extension)).write_bytes(name.encode())
            owned = root / 'development'
            retained = []
            connect = sqlite3.connect

            def track(*args, **kwargs):
                connection = connect(*args, **kwargs)
                retained.append(connection)  # Never let GC hide an unclosed handle.
                return connection

            def initialize(args, password=None):
                self.assertEqual(args[0], 'init')
                self.assertGreaterEqual(len(password), 12)
                host = Path(args[args.index('--root') + 1])
                (host / 'private').mkdir(parents=True)
                auth = Auth.create(host / 'private/auth.sqlite3', 'admin', password)
                if reject_update:
                    with auth.connection() as connection:
                        connection.execute("CREATE TRIGGER reject_development_password BEFORE UPDATE ON users BEGIN SELECT RAISE(ABORT, 'injected update failure'); END")
                config = dict(bind='127.0.0.1', port=dev.PORT, maintenance=False,
                              certificate_sha256='a' * 64,
                              rust_host_sha256=hashlib.sha256(b'quote-host').hexdigest(),
                              rust_worker_sha256=hashlib.sha256(b'quote-ledger').hexdigest())
                (host / 'private/service.json').write_text(json.dumps(config), encoding='utf-8')
                (host / 'service-cert.pem').write_text('isolated certificate fixture', encoding='utf-8')

            try:
                with patch.object(dev, 'ROOT', root), patch.object(dev, 'DEV', owned), \
                        patch.object(dev, 'command', side_effect=initialize), \
                        patch.object(dev.sqlite3, 'connect', side_effect=track):
                    if reject_update:
                        with self.assertRaisesRegex(sqlite3.IntegrityError, 'injected update failure'):
                            dev.prepare()
                        self.assertFalse((owned / 'desktop/bootstrap.json').exists())
                    else:
                        host = dev.prepare()
                        bootstrap = (owned / 'desktop/bootstrap.json').read_bytes()
                        self.assertEqual(dev.prepare(), host)
                        self.assertEqual((owned / 'desktop/bootstrap.json').read_bytes(), bootstrap)
                    self.assertTrue(retained)
                    for connection in retained:
                        with self.assertRaisesRegex(sqlite3.ProgrammingError, 'closed'):
                            connection.execute('SELECT 1')
                if not reject_update:
                    auth = Auth(host / 'private/auth.sqlite3')
                    self.assertEqual(auth.login('admin', '123456', 'isolated-test')['role'], 'admin')
                else:
                    with closing(connect(owned / 'host/private/auth.sqlite3')) as connection:
                        self.assertEqual(connection.execute('SELECT count(*) FROM users').fetchone()[0], 1)
            finally:
                for connection in retained:
                    connection.close()

    def test_initialization_commits_login_and_releases_all_handles_before_startup(self):
        self.run_prepare()

    def test_failed_initialization_releases_all_handles_and_does_not_publish_bootstrap(self):
        self.run_prepare(reject_update=True)


class DevelopmentShutdownTests(unittest.TestCase):
    def test_desktop_normal_exit_keeps_service_alive_until_private_shutdown(self):
        with tempfile.TemporaryDirectory() as folder:
            receipt = Path(folder) / 'stopped.txt'
            code = "import sys;from pathlib import Path;assert sys.stdin.buffer.readline()==b'\\n';Path(sys.argv[1]).write_text('graceful')"
            host = subprocess.Popen([sys.executable, '-c', code, str(receipt)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            try:
                self.assertEqual(dev.wait_desktop([sys.executable, '-c', 'pass']), 0)
                self.assertIsNone(host.poll())
                dev.stop_host(host)
                self.assertEqual(receipt.read_text(), 'graceful')
                self.assertEqual(host.returncode, 0)
            finally:
                if host.poll() is None:
                    host.kill(); host.communicate(timeout=5)

    def test_real_desktop_failure_is_not_relabelled_normal_close(self):
        with self.assertRaisesRegex(RuntimeError, 'DEVELOPMENT_DESKTOP_EXIT_FAILED: 7'):
            dev.wait_desktop([sys.executable, '-c', 'raise SystemExit(7)'])

    def test_real_host_failure_remains_an_error(self):
        host = subprocess.Popen([sys.executable, '-c', 'raise SystemExit(9)'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        host.wait(timeout=5)
        with self.assertRaisesRegex(RuntimeError, 'DEVELOPMENT_HOST_EXIT_FAILED: 9'):
            dev.stop_host(host)


if __name__ == '__main__':
    unittest.main()
