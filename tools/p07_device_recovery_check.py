"""Audit device-free recovery against the selected immutable daily snapshot."""
from contextlib import closing
import hashlib
import json
import sqlite3

from native_host_fixture import backup_pair, command, restore_data_backup


def check_daily_device_restore(host, admin, *, entry=None):
    if entry is None:
        entry = admin.request('POST', '/v1/backup', {'kind': 'daily'})
    package = backup_pair(host, entry) / 'data.qbackup'
    raw = package.read_bytes()
    data = json.loads(raw)['data']
    expected = data['inventory']
    assert data['snapshot_id'] == entry['backup_id'], 'RESTORE_SNAPSHOT_ID_MISMATCH'
    assert data['business_date'] == entry['business_date'], 'RESTORE_BUSINESS_DATE_MISMATCH'
    assert expected['ledger_id'] == host.config['ledger_id'], 'RESTORE_LEDGER_ID_MISMATCH'
    live = host.service.ledger.inventory()
    target = host.root / 'restored'
    receipt = restore_data_backup(host, entry, target)
    for label, actual in [('source', receipt['source_inventory']),
                          ('receipt', receipt['inventory']),
                          ('inspect', command('inspect', root=target)['inventory'])]:
        assert actual == expected, f'RESTORE_INVENTORY_MISMATCH ({label}): {actual!r} != {expected!r}'
    # Inventory checks totals/counts; row equality also protects identities,
    # customer details, every revision, note, request and audit field.
    with closing(sqlite3.connect(target / 'private/ledger.sqlite3')) as connection:
        for name, table in data['ledger'].items():
            quoted = '"' + name.replace('"', '""') + '"'
            cursor = connection.execute('SELECT * FROM ' + quoted + ' ORDER BY rowid')
            assert [column[0] for column in cursor.description] == table['columns'], f'RESTORE_COLUMNS_MISMATCH: {name}'
            assert [list(row) for row in cursor] == table['rows'], f'RESTORE_ROWS_MISMATCH: {name}'
    assert not (target / 'private/devices.sqlite3').exists(), 'RESTORE_RETAINED_DEVICE_CREDENTIALS'
    with closing(sqlite3.connect(target / 'private/auth.sqlite3')) as connection:
        assert connection.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0, 'RESTORE_RETAINED_SESSIONS'
        assert connection.execute('SELECT username FROM users WHERE enabled=1').fetchall() == [('recovered-manager',)], 'RESTORE_ENABLED_OLD_CREDENTIALS'
    assert host.service.ledger.inventory() == live, 'RESTORE_MUTATED_SOURCE_LEDGER'
    assert package.read_bytes() == raw, 'RESTORE_MUTATED_DAILY_SNAPSHOT'
    return {
        'snapshot_id': data['snapshot_id'],
        'business_date': data['business_date'],
        'package_sha256': hashlib.sha256(raw).hexdigest(),
        'source_inventory': expected,
        'restored_inventory': receipt['inventory'],
        'live_inventory': live,
        'snapshot_differs_from_live': expected != live,
        'exact_ledger_tables_checked': sorted(data['ledger']),
    }
