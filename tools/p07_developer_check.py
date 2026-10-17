"""Real developer controller + native host data/backup check in owned synthetic roots."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import sqlite3
from contextlib import closing
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from p07_developer import Developer
from p07_dev_host import command, stop_host
from quote_service.client import Client
from quote_service.journal import MemoryJournal
from quote_core import QuoteSnapshot, NormalLine, DraftDetails


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, help='Parent for a new owned verification directory')
    parser.add_argument('--readonly-destination', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(task='P07-06', platform=os.name, scope='real debug native IPC, private controller and Rust HTTPS; no UI substitute', credential_storage='Windows DPAPI' if os.name == 'nt' else 'isolated auxiliary plaintext', checks=[], status='running', production_paths_accessed=False)
    controller = None
    native = None
    local_temporary = tempfile.TemporaryDirectory(prefix='777-path-client-')
    temporary = tempfile.TemporaryDirectory(prefix='777-developer-check-', dir=args.workspace)
    try:
        if True:
            base = Path(temporary.name).resolve()
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            devdir = Path(local_temporary.name).resolve() / 'development'; devdir.mkdir()
            dev = SimpleNamespace(ROOT=ROOT, DEV=devdir, PORT=port, command=command, stop_host=stop_host)
            a, b = base / '账本 A', base / '账本 B'
            report['workspace'] = str(base)
            password = secrets.token_urlsafe(24)
            command(['init', '--root', str(a), '--backup-dir', str(base / '备份 A'), '--host', '127.0.0.1', '--bind', '127.0.0.1', '--port', str(port), '--admin', 'admin', '--worker', str(ROOT / 'target/release' / ('quote-ledger.exe' if os.name == 'nt' else 'quote-ledger')), '--notices', str(ROOT / 'THIRD_PARTY_NOTICES.md')], password)
            controller = Developer(dev, a, None)
            controller.user, controller.password = 'admin', password
            controller.remember(a, 'admin', password)
            controller.process = controller.start(a)
            controller.serve()
            profile = devdir / 'desktop'; profile.mkdir()
            (profile / '777-isolated-profile.json').write_text('{"production":false}')
            native = subprocess.Popen([str(ROOT / 'target/debug/examples' / ('developer-bridge.exe' if os.name == 'nt' else 'developer-bridge')), str(profile)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8')
            def ipc(action, **data):
                native.stdin.write(json.dumps(dict(action=action, **data)) + '\n'); native.stdin.flush()
                value = json.loads(native.stdout.readline())
                if 'error' in value:raise RuntimeError(json.dumps(value['error']))
                return value['ok']
            ipc('bootstrap')
            assert ipc('developer', request={'op':'status'})['ledger_id'] == controller.status()['ledger_id']

            def client():
                cfg = controller.config()
                c = Client(dict(schema='777-service-client-v1', url=f'https://127.0.0.1:{port}', certificate=str(controller.root / 'service-cert.pem'), certificate_sha256=cfg['certificate_sha256'], username=controller.user))
                c.login(controller.user, controller.password)
                return c

            def seed(tag, sale):
                c = client()
                try:
                    c.mutate('/v1/prices', dict(expected_price_version_id=None, prices=dict(price_version_id=tag, items=[dict(product_id='单件', sale=sale, cost='4', k='1', single=True)])), MemoryJournal())
                    order = c.submit(QuoteSnapshot(tag, (NormalLine('单件','2'),)), DraftDetails(tag, '00003', '隔离检查'), MemoryJournal())
                    return order
                finally:c.logout()

            order_a = seed('root-a', '10')
            if os.name == 'nt' and str(a).startswith('\\\\'):
                with closing(sqlite3.connect(a / 'private/ledger.sqlite3')) as connection:
                    assert connection.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
                report['checks'].append('actual_UNC_ledger_uses_rollback_journal')
            id_a = controller.status()['ledger_id']
            ipc('developer', request=dict(op='select', root=str(b), initialize=True, backup_dir=str(base / '备份 B')))
            assert ipc('bootstrap')['session']['pricing_mode_version'] == 'final-unit-v1'
            id_b = controller.status()['ledger_id']
            assert id_a != id_b
            order_b = seed('root-b', '20')
            for root, tag, order in [(a, 'root-a', order_a), (b, 'root-b', order_b), (a, 'root-a', order_a)]:
                ipc('developer', request=dict(op='select', root=str(root), initialize=False, backup_dir=''))
                ipc('bootstrap')
                assert ipc('prices')['price_version_id'] == tag
                c = client()
                try:
                    assert c.request('GET', '/v1/prices')['price_version_id'] == tag
                    result = c.request('GET', '/v1/orders')
                    assert result['total'] == 1 and result['orders'][0]['order_id'] == order['order_id']
                    assert result['totals']['income_cents'] == order['income_cents']
                finally:c.logout()
            report['checks'].append('A_B_A_real_prices_orders_and_exact_totals_isolated')
            # Exercise published Excel/image destinations through the same native IPC as the UI.
            exports = base / '共享 输出'; exports.mkdir()
            for directory in [exports, devdir]:
                settings = ipc('settings')
                ipc('save_settings', revision=str(settings['revision']), export_dir=str(directory), image_dir=str(directory))
                for kind, suffix in [('excel_quote', '.xlsx')] + ([('quote_png', '.png')] if os.name == 'nt' else []):
                    job = ipc('create_output', order_id=order_a['order_id'], expected_revision=str(order_a['revision']), kind=kind)
                    deadline = time.monotonic() + 45
                    while True:
                        found = next(j for j in ipc('outputs')['jobs'] if j['job_id'] == job['job_id'])
                        if found['state'] == 'done':break
                        assert found['state'] != 'failed' and time.monotonic() < deadline, found
                        time.sleep(.1)
                    assert list(directory.glob('*' + suffix)), found
            report['checks'].append('native_selected_directories_actual_Excel_and_Windows_PNG_outputs')
            before = controller.preferences_file.read_bytes()
            unknown = base / 'unknown'; unknown.mkdir(); (unknown / 'keep.txt').write_text('preserve')
            try:controller.select(str(unknown), initialize=True, backup_dir=str(base / 'other backup'))
            except RuntimeError as e:assert str(e) == 'DEVELOPER_EMPTY_DIRECTORY_REQUIRED'
            else:raise AssertionError('unknown data accepted')
            assert before == controller.preferences_file.read_bytes() and controller.root == a
            report['checks'].append('nonempty_initialization_keeps_original_files_and_active_source')
            old_backup = Path(controller.config()['backup_dir'])
            old_files = {str(p.relative_to(old_backup)):hashlib.sha256(p.read_bytes()).hexdigest() for p in old_backup.rglob('*') if p.is_file()}
            target = base / '新的 备份位置'
            hidden = base / '隐藏 数据'
            target.mkdir(); hidden.mkdir()
            for directory in [target, hidden]:(directory / 'keep.txt').write_bytes(b'existing user file')
            attributes = None
            if os.name == 'nt':
                import ctypes
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.GetFileAttributesW.argtypes = [ctypes.c_wchar_p]
                kernel.GetFileAttributesW.restype = ctypes.c_uint32
                kernel.SetFileAttributesW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
                kernel.SetFileAttributesW.restype = ctypes.c_int
                attributes = kernel.GetFileAttributesW(str(hidden)) | 6
                assert kernel.SetFileAttributesW(str(hidden), attributes)

            state = ipc('developer', request=dict(op='daily_backup', directory=str(target), hidden=str(hidden), hour=23))
            assert state['backup_dir'] == str(target) and state['daily']['hidden_dir'] == str(hidden)
            for directory in [target, hidden]:assert (directory / 'keep.txt').read_bytes() == b'existing user file'
            if attributes is not None:assert kernel.GetFileAttributesW(str(hidden)) == attributes
            report['checks'].append('populated_destinations_preserve_existing_files_and_hidden_system_attributes')
            if args.workspace:
                # Bypass Python canonicalization once: the Rust CLI must accept the original mapped drive itself.
                controller.dev.stop_host(controller.process); controller.process = None
                try:
                    command(['configure-daily', '--root', str(a), '--backup-dir', str(args.workspace / base.name / target.name),
                             '--hidden-dir', str(hidden), '--daily-hour', '23', '--admin', controller.user], controller.password)
                finally:controller.process = controller.start(a)
                report['checks'].append('raw_selected_alias_accepted_by_Rust_CLI_and_same_backup_identity_reused')
            if args.readonly_destination:
                before_config = controller.config()
                try:controller.configure_daily(str(target), str(args.readonly_destination), 23)
                except RuntimeError as error:assert 'PATH_PERMISSION_DENIED' in str(error), str(error)
                else:raise AssertionError('READ_ONLY_SHARE_ACCEPTED')
                assert controller.config() == before_config
                assert controller.status()['daily']['hidden_dir'] == str(hidden)
                report['checks'].append('read_only_share_reports_permission_denied_and_preserves_configuration')
            assert json.loads((target / '777-backups.json').read_text(encoding='utf-8'))['last_success'] is None
            c = client()
            try:
                public=c.request('GET','/v1/backup')
                assert str(hidden) not in json.dumps(public) and 'hidden_dir' not in json.dumps(public)
                from quote_service.protocol import APIError
                try:c.request('POST','/v1/backup-plan',dict(daily_hour=0))
                except APIError as e:assert e.status==403
                else:raise AssertionError('PUBLIC_BACKUP_PLAN_MUTATION_ACCEPTED')
                entry=c.request('POST','/v1/backup',dict(kind='daily'))
                assert c.request('POST','/v1/backup',dict(kind='daily'))==entry
                folder = id_a+'-'+entry['business_date']+'-'+entry['backup_id']
                pair = target / folder
                assert {p.name for p in pair.iterdir()}=={'data.qbackup','data.xlsx'}
                hashes={name:hashlib.sha256((pair/name).read_bytes()).hexdigest() for name in ['data.qbackup','data.xlsx']}
                assert all((pair/n).read_bytes()==(hidden/folder/n).read_bytes() for n in hashes)
                parked=hidden.with_name('hidden temporarily offline');hidden.rename(parked);hidden.write_text('unavailable')
                try:
                    assert c.request('POST','/v1/backup',dict(kind='daily'))==entry
                    health=controller.status()['daily_result']
                    assert health['normal']['ok'] and not health['hidden']['ok']
                finally:hidden.unlink();parked.rename(hidden)
                c.request('POST','/v1/backup',dict(kind='daily'))
                assert controller.status()['daily_result']['hidden']['ok']
                parked=target.with_name('normal temporarily offline');target.rename(parked);target.write_text('unavailable')
                try:
                    try:c.request('POST','/v1/backup',dict(kind='daily'))
                    except APIError:pass
                    else:raise AssertionError('FAILED_NORMAL_BACKUP_REPORTED_SUCCESS')
                    health=controller.status()['daily_result']
                    assert not health['normal']['ok'] and health['hidden']['ok']
                finally:target.unlink();parked.rename(target)
                assert c.request('POST','/v1/backup',dict(kind='daily'))==entry
            finally:c.logout()
            assert hashes=={n:hashlib.sha256((pair/n).read_bytes()).hexdigest() for n in hashes}
            assert old_files == {str(p.relative_to(old_backup)):hashlib.sha256(p.read_bytes()).hexdigest() for p in old_backup.rglob('*') if p.is_file()}
            report['backup']=dict(ledger_id=id_a,snapshot_id=entry['backup_id'],hashes=hashes,bytes={n:(pair/n).stat().st_size for n in hashes})
            report['checks'].append('dual_formats_identical_in_both_destinations_independent_failures_retry_same_snapshot_no_legacy_deletion')
            report['checks'].append('public_API_cannot_change_daily_policy_or_observe_hidden_destination')
            # User regression: current ordinary directory exists but its index is missing.
            # Both public developer setters must repair it before reading status.
            # Previously daily save rolled back an already validated hidden UNC destination.
            saved_config = controller.config()
            marker = target / '777-backups.json'
            preserved = {str(p.relative_to(target)):hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in target.rglob('*') if p.is_file() and p != marker}
            for operation in ['daily_backup', 'backup_directory']:
                marker.unlink()
                if operation == 'daily_backup':
                    state = ipc('developer', request=dict(op=operation, directory=str(target), hidden=str(hidden), hour=23))
                else:
                    state = ipc('developer', request=dict(op=operation, directory=str(target)))
                assert state['daily']['hidden_dir'] == str(hidden)
                assert controller.config() == saved_config
                assert json.loads(marker.read_text(encoding='utf-8'))['store_id'] == saved_config['backup_store_id']
                assert preserved == {str(p.relative_to(target)):hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in target.rglob('*') if p.is_file() and p != marker}
                c = client()
                try:assert c.request('POST','/v1/backup',dict(kind='daily')) == entry
                finally:c.logout()
                assert controller.status()['daily_result']['hidden']['ok']
                assert hashes == {n:hashlib.sha256((pair/n).read_bytes()).hexdigest() for n in hashes}
            original_marker = marker.read_bytes()
            for damaged in [b'corrupt index', json.dumps({**json.loads(original_marker), 'store_id':'00000000-0000-4000-8000-000000000001'}).encode()]:
                marker.write_bytes(damaged)
                try:
                    ipc('developer', request=dict(op='daily_backup', directory=str(target), hidden=str(hidden), hour=23))
                except RuntimeError:pass
                else:raise AssertionError('EXISTING_INVALID_INDEX_OVERWRITTEN')
                assert marker.read_bytes() == damaged and controller.config() == saved_config
                marker.write_bytes(original_marker)
            report['checks'].append('missing_current_index_resaved_by_both_setters_preserves_identity_files_snapshot_and_hidden_configuration')
            report['checks'].append('corrupt_or_foreign_current_index_rejected_without_overwrite_or_configuration_loss')
            from openpyxl import load_workbook
            book=load_workbook(pair/'data.xlsx',read_only=True)
            try:
                rows=list(book['账本_orders'].values); assert len(rows)==2
                assert rows[1][rows[0].index('income_cents')]==order_a['income_cents']
                assert all(cell.data_type!='f' for sheet in book for row in sheet for cell in row)
            finally:book.close()
            original_bytes=(pair/'data.qbackup').read_bytes()
            invalid=base/'invalid.qbackup'
            for field,value in [('sha256','0'*64),('format','777-data-backup-v999')]:
                damaged=json.loads(original_bytes);damaged[field]=value;invalid.write_text(json.dumps(damaged),encoding='utf-8')
                try:ipc('developer',request=dict(op='restore_data',package=str(invalid),target=str(base/'refused')))
                except RuntimeError:pass
                else:raise AssertionError('INVALID_RECOVERY_ACCEPTED')
                assert controller.root==a and not (base/'refused').exists()
            restored=base/'恢复 账本'
            state=ipc('developer',request=dict(op='restore_data',package=str(pair/'data.qbackup'),target=str(restored)))
            ipc('bootstrap');assert state['ledger_id']==id_a and state['daily']['hidden_dir']==str(hidden)
            c=client()
            try:
                result=c.request('GET','/v1/orders');assert result['total']==1 and result['orders'][0]['order_id']==order_a['order_id']
                assert result['totals']['income_cents']==order_a['income_cents']
                assert c.request('POST','/v1/backup',dict(kind='daily'))['backup_id']==entry['backup_id']
                assert controller.status()['daily_result']['hidden']['ok']
            finally:c.logout()
            try:ipc('developer',request=dict(op='restore_data',package=str(pair/'data.qbackup'),target=str(restored)))
            except RuntimeError:pass
            else:raise AssertionError('EXISTING_RESTORE_TARGET_OVERWRITTEN')
            ipc('developer',request=dict(op='select',root=str(a),initialize=False,backup_dir=''));ipc('bootstrap')
            report['checks'].append('real_native_import_restores_business_view_preserves_original_rejects_corruption_future_version_and_overwrite')
            controller.handle(dict(op='save_package', output=str(base / '安装包'), version='0.1.0', runtime='downloadBootstrapper'))
            native.communicate(timeout=15); assert native.returncode == 0; native = None
            controller.close(); controller = None
            controller = Developer(dev, a, None)
            assert controller.preferences['root'] == str(a)
            assert controller.preferences['output'] == str(base / '安装包')
            controller.user, controller.password = controller.credentials[str(a)]['user'], controller.credentials[str(a)]['password']
            controller.process = controller.start(a)
            c = client()
            try:assert c.request('GET', '/v1/orders')['total'] == 1
            finally:c.logout()
            report['checks'].append('saved_config_and_credentials_restart_with_same_actual_ledger')
            controller.close(); controller = None
        report['status'] = 'passed'
    except BaseException as e:
        report['status'] = 'failed'; report['error'] = type(e).__name__ + ': ' + str(e)
        raise
    finally:
        if native:native.communicate(timeout=15)
        if controller:controller.close()
        temporary.cleanup()
        local_temporary.cleanup()
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':main()
