"""Complete host recovery, offline authority gate and missing-target behavior."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from dataclasses import asdict

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from service_fixture import Hosted
from quote_service.hosting import initialize,load
from quote_service.recovery import restore,manifest,retain
from quote_service.protocol import APIError
from quote_service.journal import MemoryJournal
from quote_core import QuoteSnapshot,NormalLine,DraftDetails


class ServiceRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.host=Hosted()
    @classmethod
    def tearDownClass(cls):cls.host.close()

    def test_complete_restore_preserves_actor_ids_ledger_cert_and_preferences_revokes_all_sessions(self):
        host=self.host;client=host.client();before_ids={r['id'] for r in host.service.auth.accounts(host.admin)}
        client.submit(QuoteSnapshot('fixture-v1',(NormalLine('单件','2'),)),DraftDetails(),MemoryJournal())
        entry=host.service.backup(kind='maintenance');target=host.root/'restored-host'
        ledger,auth=restore(entry['service_bundle'],target,'manager','recovery-new-password',auxiliary=os.name!='nt')
        self.assertEqual(ledger.inventory(),host.service.ledger.inventory());self.assertTrue(entry['full_service_verified'])
        identity=auth.login('manager','recovery-new-password','fixture');actor=auth.authenticate(identity['token'])
        self.assertEqual({r['id'] for r in auth.accounts(actor)},before_ids)
        self.assertEqual(auth.preferences(),host.service.auth.preferences())
        self.assertEqual((target/'private/tls-cert.pem').read_bytes(),(host.root/'host/private/tls-cert.pem').read_bytes())
        with self.assertRaises(APIError):auth.authenticate(client.token)
        with self.assertRaises(APIError):auth.login('sales-one',host.password,'fixture')
        with self.assertRaises(APIError) as caught:load(target,auxiliary=os.name!='nt')
        self.assertEqual(caught.exception.code,'RECOVERY_MAINTENANCE_REQUIRED')
        with self.assertRaises(FileExistsError):restore(entry['service_bundle'],target,'manager','recovery-new-password',auxiliary=os.name!='nt')

    def test_missing_backup_target_does_not_stop_primary_service_or_undo_order(self):
        host=self.host;original=host.service.backups.root
        host.service.backups.root=host.root/'missing-backup'
        try:
            client=host.client();result=client.submit(QuoteSnapshot('fixture-v1',(NormalLine('单件','1'),)),DraftDetails(),MemoryJournal())
            with self.assertRaises(Exception):host.service.backup(kind='maintenance')
            status=host.client('manager').request('GET','/v1/backup')
            self.assertEqual(status['status'],'unavailable');self.assertIsNotNone(status['service_health']['error'])
            self.assertEqual(client.request('GET','/v1/orders/'+result['order_id'])['income_cents'],'1000')
        finally:host.service.backups.root=original

    def test_corrupt_bundle_and_foreign_files_refuse_restore_before_creating_target(self):
        entry=self.host.service.backup(kind='maintenance');folder=Path(entry['service_bundle']);marker=folder/'foreign.txt';marker.write_text('leave')
        target=self.host.root/'refused-target'
        try:
            with self.assertRaises(APIError):restore(folder,target,'manager','recovery-new-password',auxiliary=os.name!='nt')
            self.assertFalse(target.exists());self.assertEqual(marker.read_text(),'leave')
        finally:marker.unlink()
        database=folder/'auth.sqlite3';original=database.read_bytes();database.write_bytes(original+b'changed')
        try:
            with self.assertRaises(APIError):manifest(folder)
            self.assertFalse(target.exists())
        finally:database.write_bytes(original)

    def test_failed_identity_bundle_does_not_replace_last_verified_service_success(self):
        first=self.host.service.backup(kind='maintenance');before=self.host.service.auth.backup_health()
        with patch('quote_service.recovery.bundle',side_effect=OSError('injected identity packaging failure')):
            with self.assertRaises(OSError):self.host.service.backup(kind='maintenance')
        after=self.host.service.auth.backup_health();self.assertEqual(after['last_success'],first);self.assertIsNotNone(after['error'])

    def test_init_invalid_password_or_existing_root_does_not_adopt_existing_content(self):
        target=self.host.root/'invalid-init';backup=self.host.root/'invalid-init-backup'
        with self.assertRaises(APIError):initialize(target,backup,'manager','short',hosts=['127.0.0.1'],auxiliary=os.name!='nt')
        self.assertFalse(target.exists());self.assertFalse(backup.exists())
        target.mkdir();marker=target/'foreign.txt';marker.write_text('keep')
        with self.assertRaises(FileExistsError):initialize(target,backup,'manager','valid-fixture-password',hosts=['127.0.0.1'],auxiliary=os.name!='nt')
        self.assertEqual(marker.read_text(),'keep');self.assertFalse(backup.exists())


if __name__=='__main__':unittest.main()
