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
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(task='P07-05', platform=os.name, scope='real debug native IPC, private controller and Rust HTTPS; no UI substitute', credential_storage='Windows DPAPI' if os.name == 'nt' else 'isolated auxiliary plaintext', checks=[], status='running', production_paths_accessed=False)
    controller = None
    native = None
    temporary = tempfile.TemporaryDirectory(prefix='777-developer-check-')
    try:
        if True:
            base = Path(temporary.name).resolve()
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            devdir = base / 'development'; devdir.mkdir()
            dev = SimpleNamespace(ROOT=ROOT, DEV=devdir, PORT=port, command=command, stop_host=stop_host)
            a, b = base / '账本 A', base / '账本 B'
            password = secrets.token_urlsafe(24)
            command(['init', '--root', str(a), '--backup-dir', str(base / '备份 A'), '--host', '127.0.0.1', '--bind', '127.0.0.1', '--port', str(port), '--admin', 'admin', '--worker', str(ROOT / 'target/release' / ('quote-ledger.exe' if os.name == 'nt' else 'quote-ledger')), '--notices', str(ROOT / 'THIRD_PARTY_NOTICES.md')], password)
            controller = Developer(dev, a, None)
            controller.user, controller.password = 'admin', password
            controller.remember(a, 'admin', password)
            controller.process = controller.start(a)
            controller.serve()
            profile = base / 'desktop'; profile.mkdir()
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
            state = ipc('developer', request=dict(op='backup_directory', directory=str(target)))
            assert state['backup_dir'] == str(target)
            marker = json.loads((target / '777-backups.json').read_text())
            entry = json.loads((target / '777-service-backups.json').read_text())['entries'][-1]
            assert entry['full_service_verified'] and entry['verified_restore']
            bundle = Path(entry['service_bundle'])
            assert json.loads((bundle / 'manifest.json').read_text())['ledger_id'] == id_a
            assert old_files == {str(p.relative_to(old_backup)):hashlib.sha256(p.read_bytes()).hexdigest() for p in old_backup.rglob('*') if p.is_file()}
            report['backup'] = dict(ledger_id=id_a, manifest_sha256=hashlib.sha256((bundle / 'manifest.json').read_bytes()).hexdigest(), full_service_verified=True)
            report['checks'].append('new_backup_directory_full_bundle_independent_restore_and_old_backup_retained')
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
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':main()
