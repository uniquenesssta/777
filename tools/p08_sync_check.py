"""Two real Windows Rust TLS hosts: one ledger, async snapshots and outage safety."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(ROOT / 'tools')]
from native_host_fixture import Hosted, command, WORKER
from p01_validation import new_output
from quote_service.client import Client
from quote_service.protocol import APIError


def until(check, timeout=45):
    deadline = time.monotonic() + timeout
    while True:
        result = check()
        if result:
            return result
        if time.monotonic() >= deadline:
            raise AssertionError('SYNC_CONDITION_TIMED_OUT')
        time.sleep(.2)


def publication(root):
    private = root / 'private/cluster'
    pointer = json.loads((private / 'current.json').read_bytes())
    return private / 'generations' / f"{pointer['generation']:020}_{pointer['sha256']}"


def inventory(root):
    with sqlite3.connect(publication(root) / 'ledger.sqlite3') as database:
        database.row_factory = sqlite3.Row
        from quote_ledger.store import inventory as read
        return read(database)


def refused(call, code):
    try:
        call()
    except APIError as error:
        assert error.code == code, (error.code, code)
    else:
        raise AssertionError('REQUEST_WAS_NOT_REFUSED')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Actual Windows hosts are required for this product check')
    output = new_output(args.output)
    report = dict(task='P08-02', scope='two_owned_Windows_Rust_TLS_hosts', status='failed', live_hosts_contacted=False,
                  installers_built=False, automatic_failover=False, checks=[])
    os.environ['QUOTE777_LOG_ROOT'] = str(output)
    checks = report['checks']
    primary = follower = None
    try:
        primary = Hosted()
        primary.stop()
        command('enable-devices', root=primary.host_root, admin='manager', secret=primary.password)
        command('cluster-primary', root=primary.host_root, admin='manager', secret=primary.password)
        primary.start()
        admin = primary.client('manager')
        invitation = command('cluster-invite', root=primary.host_root, admin='manager', secret=primary.password)
        # The ticket is confined to this owned temporary fixture, never evidence.
        invitation_path = primary.root / 'join.777join'
        invitation_path.write_text(json.dumps(invitation), encoding='utf-8')
        follower = Hosted.__new__(Hosted)
        follower.temp = tempfile.TemporaryDirectory(prefix='777-replica-check-')
        follower.root = Path(follower.temp.name)
        follower.host_root = follower.root / 'host'
        follower.password = primary.password
        follower.font = None
        follower.process = None
        follower.fault = follower.host_root / 'private/test-fault.txt'
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0)); follower.port = probe.getsockname()[1]
        joining = dict(root=follower.host_root, invitation=invitation_path, backup_dir=follower.root / 'backups',
                       host=['127.0.0.1', 'localhost'], port=follower.port, worker=WORKER, notices=ROOT / 'THIRD_PARTY_NOTICES.md')
        joined = command('cluster-join', **joining)
        follower.config = json.loads((follower.host_root / 'private/service.json').read_bytes())
        assert joined['status'] == 'joined_stopped'
        assert follower.config['ledger_id'] == primary.config['ledger_id']
        assert follower.config['certificate_sha256'] != primary.config['certificate_sha256']
        assert (follower.host_root / 'private/tls-key.pem').read_bytes() != (primary.host_root / 'private/tls-key.pem').read_bytes()
        assert command('cluster-join', **joining)['node_id'] == joined['cluster']['node_id']
        before_auth = hashlib.sha256((publication(follower.host_root) / 'auth.sqlite3').read_bytes()).hexdigest()
        try:
            command('cluster-primary', root=follower.host_root, admin='manager', secret=primary.password)
        except RuntimeError as error:
            assert 'CLUSTER_REPLICA_CANNOT_WRITE' in str(error)
        else:
            raise AssertionError('REPLICA_PROMOTION_WAS_ALLOWED')
        assert hashlib.sha256((publication(follower.host_root) / 'auth.sqlite3').read_bytes()).hexdigest() == before_auth
        from p08_sync_bundle import check as check_bundle
        bundle_invitation = primary.root / 'bundle.777join'
        bundle_invitation.write_text(json.dumps(command('cluster-invite', root=primary.host_root, admin='manager', secret=primary.password)), encoding='utf-8')
        check_bundle(primary, primary.root, bundle_invitation, follower.port, ROOT)
        checks.append('Windows_PowerShell_5_1_portable_join_without_SDKs_creates_owned_deployment_and_public_connection')
        follower.start()
        remote = follower.client('manager')
        assert remote.request('GET', '/v1/capabilities')['protocol'] == '777-service-v1'
        assert remote.request('GET', '/v1/prices') == admin.request('GET', '/v1/prices')
        checks.append('fresh_join_same_ledger_accounts_prices_independent_TLS_and_repeatable_join')
        # Every operation through the replica is authorized/committed by the primary.
        shot = dict(price_version_id='fixture-v1', rule_version='business-v1', numeric_profile='numeric-v1',
                    lines=[dict(line_kind='normal', product_id='单件', q='2', h='', w='', name='')])
        payload = dict(request_id=str(uuid.uuid4()), snapshot=shot, details=dict(customer='同步客户', order_ref='000001', wechat='sync-wx'))
        receipt = remote.request('POST', '/v1/orders', payload)
        assert remote.request('POST', '/v1/orders', payload) == receipt
        order = admin.request('GET', '/v1/orders/' + receipt['order_id'])
        shot['lines'][0]['q'] = '3'
        edit = dict(request_id=str(uuid.uuid4()), order_id=order['order_id'], expected_revision=int(order['revision']), snapshot=shot,
                    sources=[order['lines'][0]['line_id']], details=order['details'], customer=dict(customer_id=order['customer_id']))
        edited = remote.request('POST', '/v1/order-save', edit)
        assert str(edited['revision']) == '2'
        assert admin.request('GET', '/v1/orders/' + order['order_id'])['income_cents'] == '3000'
        until(lambda: inventory(follower.host_root)['counts']['orders'] == 1 and inventory(follower.host_root)['active_income_cents'] == '3000')
        checks.append('replica_forwards_order_create_retry_and_edit_once_with_frozen_revision_history')
        job = remote.request('POST', '/v1/outputs', dict(request_id=str(uuid.uuid4()), order_id=order['order_id'], expected_revision=2, kind='excel_quote'))
        records = until(lambda: next((j for j in admin.request('GET', '/v1/outputs')['jobs'] if j['job_id'] == job['job_id'] and j['state'] == 'done'), None))
        blob = base64.b64decode(remote.request('GET', '/v1/outputs/' + job['job_id'] + '/content')['data_base64'])
        digest = hashlib.sha256(blob).hexdigest()
        until(lambda: any(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p in (publication(follower.host_root) / 'output-blobs').glob('*.xlsx')))
        checks.append('completed_output_metadata_and_exact_readable_Excel_blob_replicated')
        # Replaying the used ticket with a different node/secret is refused.
        stranger = dict(invitation, node_id=str(uuid.uuid4()), credential='B' * 43)
        stranger = {k: stranger[k] for k in ('cluster_id', 'ledger_id', 'grant_id', 'ticket', 'node_id', 'credential')}
        refused(lambda: admin.request('POST', '/v1/cluster/enroll', stranger), 'CLUSTER_INVITATION_ALREADY_USED')
        checks.append('single_use_join_ticket_replay_rejected')
        # An ordinary desktop device enrolled on the primary can authenticate via either node.
        account = next(x for x in admin.request('GET', '/v1/accounts')['accounts'] if x['username'] == 'sales-one')
        grant = admin.request('POST', '/v1/device-grants', dict(subject=account['id'], delivery='sales', ttl_seconds=60))
        device_id, device_secret = str(uuid.uuid4()), 'C' * 43
        remote.request('POST', '/v1/device/enroll', dict(ticket=grant['ticket'], device_id=device_id, device_secret=device_secret, delivery='sales'))
        session = remote.request('POST', '/v1/device/session', dict(device_id=device_id, device_secret=device_secret, delivery='sales'))
        devices = until(lambda: _device_state(follower.host_root, device_id, 1))
        admin.request('POST', '/v1/devices/' + device_id, {})
        until(lambda: _device_state(follower.host_root, device_id, 0))
        refused(lambda: remote.request('POST', '/v1/device/session', dict(device_id=device_id, device_secret=device_secret, delivery='sales')), 'DEVICE_NOT_AUTHORIZED')
        checks.append('stable_device_identity_and_revocation_replicated_and_enforced_by_primary')
        before = inventory(follower.host_root)
        primary.stop()
        outage = dict(payload, request_id=str(uuid.uuid4()), details=dict(customer='断线', order_ref='000002', wechat=''))
        refused(lambda: remote.request('POST', '/v1/orders', outage), 'CLUSTER_PRIMARY_UNREACHABLE_OR_CERTIFICATE_REJECTED')
        assert inventory(follower.host_root) == before
        until(lambda: command('cluster-status', root=follower.host_root)['state']['phase'] == 'disconnected')
        primary.start()
        # The original user session and request ID remain valid after source restart.
        remote.request('POST', '/v1/orders', outage)
        until(lambda: inventory(follower.host_root)['counts']['orders'] == 2)
        checks.append('primary_outage_never_writes_replica_and_reconnect_preserves_session_and_request_identity')
        follower.stop()
        # A TLS-authenticated damaged file cannot replace the last good generation.
        old_pointer = json.loads((follower.host_root / 'private/cluster/current.json').read_bytes())
        admin = primary.client('manager')
        admin.request('POST', '/v1/orders', dict(payload, request_id=str(uuid.uuid4()), details=dict(customer='坏块隔离', order_ref='000004', wechat='')))
        until(lambda: inventory(primary.host_root)['counts']['orders'] == 3)
        primary.stop()
        from p08_sync_fault import DamagedTransfer
        with DamagedTransfer(primary) as damaged:
            follower.start()
            until(lambda: command('cluster-status', root=follower.host_root)['state'].get('error') == 'CLUSTER_FILE_HASH_INVALID')
            assert json.loads((follower.host_root / 'private/cluster/current.json').read_bytes()) == old_pointer
            follower.stop()
            damaged.seed_partial(follower)
            follower.start()
            until(lambda: inventory(follower.host_root)['counts']['orders'] == 3)
            assert ('ledger.sqlite3', 4096) in damaged.offsets
            follower.stop()
        primary.start()
        checks.append('damaged_TLS_chunk_rejected_last_generation_retained_and_restart_resumes_verified_partial_offset')
        # An interrupted staging directory is removed without changing the last complete generation.
        orphan = follower.host_root / 'private/cluster' / ('stage-' + str(uuid.uuid4()))
        orphan.mkdir(); (orphan / 'unfinished').write_bytes(b'incomplete')
        admin = primary.client('manager')
        admin.request('POST', '/v1/orders', dict(payload, request_id=str(uuid.uuid4()), details=dict(customer='继续同步', order_ref='000003', wechat='')))
        follower.start()
        until(lambda: inventory(follower.host_root)['counts']['orders'] == 4)
        assert not orphan.exists()
        checks.append('restart_catches_up_and_cleans_interrupted_stage_without_partial_publication')
        node = joined['cluster']['node_id']
        admin.request('POST', '/v1/cluster/revoke', dict(node_id=node))
        refused(lambda: remote.request('GET', '/v1/prices'), 'CLUSTER_PEER_REVOKED')
        until(lambda: command('cluster-status', root=follower.host_root)['state']['phase'] == 'revoked')
        checks.append('node_revocation_immediately_blocks_business_forwarding_and_sync')
        follower.stop(); primary.stop()
        # Re-read and verify every retained published file against its immutable manifest.
        for host in (primary, follower):
            path = publication(host.host_root)
            manifest = json.loads((path / 'manifest.json').read_bytes())
            for name, entry in manifest['files'].items():
                assert hashlib.sha256((path / name).read_bytes()).hexdigest() == entry['sha256']
            for path in output.rglob('runtime.jsonl'):
                raw = path.read_text(encoding='utf-8')
                assert primary.password not in raw and invitation['ticket'] not in raw and device_secret not in raw
                assert len(raw.splitlines()) < 1500
        checks.append('all_published_file_hashes_match_and_logs_are_bounded_without_tickets_passwords_or_payloads')
        report['status'] = 'passed'
    except Exception as exc:
        report['error_type'] = type(exc).__name__
        raise
    finally:
        try:
            if follower is not None: follower.close()
            if primary is not None: primary.close()
        finally:
            (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


def _device_state(root, device_id, enabled):
    with sqlite3.connect(publication(root) / 'devices.sqlite3') as db:
        return db.execute('SELECT count(*) FROM devices WHERE id=? AND enabled=?', (device_id, enabled)).fetchone()[0] == 1


if __name__ == '__main__':
    main()
