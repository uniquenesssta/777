"""Real TLS Host regression: an earlier daily snapshot is not the live ledger."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from native_host_fixture import Hosted, backup_pair
from p07_device_recovery_check import check_daily_device_restore
from quote_core import DraftDetails, NormalLine, QuoteSnapshot
from quote_service.journal import MemoryJournal


class NativeDeviceRecoveryTests(unittest.TestCase):
    def test_earlier_daily_snapshot_restores_exactly_after_later_orders(self):
        host = Hosted()
        try:
            admin = host.client('manager')
            entry = admin.request('POST', '/v1/backup', {'kind': 'daily'})
            raw = (backup_pair(host, entry) / 'data.qbackup').read_bytes()
            captured = json.loads(raw)['data']['inventory']
            sales = host.client()
            for index in range(2):
                sales.submit(QuoteSnapshot('fixture-v1', (NormalLine('单件', '2'),)),
                             DraftDetails('恢复回归', f'after-snapshot-{index}', ''), MemoryJournal())
            live = host.service.ledger.inventory()
            self.assertEqual(live['counts']['orders'], captured['counts']['orders'] + 2)
            # Deterministically reproduces the old equality failure without
            # changing clocks, suppressing the scheduler or replacing backup data.
            self.assertNotEqual(captured, live)
            result = check_daily_device_restore(host, admin, entry=entry)
            self.assertEqual(result['source_inventory'], captured)
            self.assertEqual(result['restored_inventory'], captured)
            self.assertEqual(result['live_inventory'], live)
            self.assertTrue(result['snapshot_differs_from_live'])
            self.assertEqual(host.service.ledger.inventory(), live)
            self.assertEqual((backup_pair(host, entry) / 'data.qbackup').read_bytes(), raw)
            print(json.dumps({'regression': self._testMethodName, 'restoration': result}, ensure_ascii=False))
        finally:
            host.close()


if __name__ == '__main__':
    unittest.main()
