"""Real primary TLS intake/application/reviewer flow, with no installer or live LAN access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(ROOT / 'tools')]
from p01_validation import new_output
from native_host_fixture import command
from p08_application import ApplicationFixture, FORMAT, identifier


def run():
    f = ApplicationFixture()
    try:
        first = f.operation(1)
        f.send(first)
        receipt = f.wait(first, 'applied')
        assert receipt['result']['income_cents'] == '1000' and 'cost_cents' not in receipt['result']
        line = first['payload']['snapshot']['lines'][0]
        def change(sequence, quantity):
            return f.operation(sequence, kind='edit', order=first['order_id'],
                               base=dict(order_revision='1', previous_operation_id=None),
                               payload=dict(detail_changes={}, line_changes=[dict(op='replace', line_id=line['line_id'],
                                            raw={**line['raw'], 'q': quantity})], customer={}))
        one, two = change(2, '2'), change(3, '3')
        f.send(one)
        f.wait(one, 'applied')
        f.send(two)
        f.wait(two, 'conflict')
        other = f.operation(4)
        f.send(other)
        f.wait(other, 'applied')
        denied = f.call('/v1/offline/review', dict(protocol=FORMAT, after=None), accepted=(403,))
        assert denied['error'] == 'OFFLINE_REVIEWER_REQUIRED'
        denied = f.call('/v1/offline/review', dict(protocol=FORMAT, after=None), token=f.admin.token, accepted=(403,))
        assert denied['error'] == 'OFFLINE_REVIEWER_REQUIRED'
        f.host.stop()
        command('set-offline-reviewer', root=f.host.host_root, admin='manager', reviewer='manager', secret=f.host.password)
        f.host.start()
        rows = f.call('/v1/offline/review', dict(protocol=FORMAT, after=None), token=f.admin.token)
        assert rows['items'][0]['operation']['operation_id'] == two['operation_id']
        decision = dict(protocol=FORMAT, request_id=identifier(), operation_id=two['operation_id'],
                        expected_revision='2', decision='apply_candidate', reason='isolated real TLS recovery check')
        resolved = f.call('/v1/offline/resolve', decision, token=f.admin.token)
        assert resolved['revision'] == 3
        before = command('inspect', root=f.host.host_root)['inventory']
        assert f.call('/v1/offline/resolve', decision, token=f.admin.token) == resolved
        assert command('inspect', root=f.host.host_root)['inventory'] == before
        assert before['counts']['orders'] == 2 and before['active_income_cents'] == '4000'
        feed = f.call('/v1/offline/changes', dict(protocol=FORMAT, cursor=None))
        chunk = f.call('/v1/offline/order-chunk', dict(protocol=FORMAT, epoch=feed['epoch'], order_id=first['order_id'],
                       revision='3', section='lines', offset='0'))
        assert chunk['items'][0]['line_id'] == line['line_id']
        assert 'cost_cents' not in json.dumps(chunk) and 'profit_cents' not in json.dumps(chunk)
        f.host.restart()
        final = f.wait(two, 'conflict')
        assert final['resolution'] == 'applied' and final['result']['revision'] == '3'
        return dict(tls_version=f.tls_version, final_inventory=before, checks=[
            'stopped_host_application_and_reviewer_CLI_with_real_password_verification',
            'real_issuer_package_enrollment_and_device_session_without_fabricated_sessions',
            'HTTPS_202_followed_by_atomic_application_and_stable_line_identity',
            'conflicting_edit_retained_while_another_order_applies',
            'formal_device_and_ungranted_password_admin_denied_review',
            'explicit_grant_resolution_and_same_ID_replay_without_double_booking',
            'bounded_capability_filtered_feed_and_order_section',
            'process_restart_retains_original_conflict_and_decision_receipt'])
    finally:
        f.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--auxiliary', action='store_true')
    args = parser.parse_args(argv)
    if os.name != 'nt' and not args.auxiliary:
        parser.error('Actual Windows is required unless explicitly collecting auxiliary evidence')
    output = new_output(args.output)
    report = dict(task='P08-02-3-C', status='running', environment=dict(os=platform.system(), python=platform.python_version()),
                  source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  worktree_dirty=bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()),
                  live_hosts_contacted=False, installers_or_build_preparation_verified=False)
    try:
        report['runtime'] = run()
        report['status'] = 'Windows_TLS_primary_application_passed_site_pending' if os.name == 'nt' else 'auxiliary_TLS_primary_application_passed_Windows_pending'
    except Exception as error:
        report['status'] = 'failed'
        report['failure'] = type(error).__name__ + ': ' + str(error)
        (output / 'failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
    files = [ROOT / name for name in ['tools/p08_application_check.py', 'tests/native_host_fixture.py', '.github/workflows/p07-windows.yml']]
    files += list((ROOT / 'tools/p08_application').glob('*.py'))
    files += [path for folder in ['crates/quote-host/src', 'crates/quote-ledger/src'] for path in (ROOT / folder).rglob('*') if path.is_file() and path.suffix in ['.rs', '.sql']]
    report['implementation_sha256_LF'] = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest() for path in sorted(files)}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'implementation_sha256_LF'}, ensure_ascii=False, indent=2))
    return 0 if 'passed' in report['status'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
