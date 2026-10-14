"""Development initialization must commit and release SQLite before host startup."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
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


if __name__ == '__main__':
    unittest.main()
