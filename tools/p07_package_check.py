"""Actual Windows NSIS lifecycle on an owned temporary service/profile, no real deployment."""
import argparse
from contextlib import closing
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(ROOT / 'tools')]
from native_host_fixture import Hosted
from p07_device_check import enable
from p07_native_window import Windows, close_window, cleanup_webview_sandbox


def run(args, *, env=None, expected=0, timeout=2400):
    result = subprocess.run(args, cwd=ROOT, env=env, timeout=timeout, check=False)
    if (expected == 0 and result.returncode != 0) or (expected == 'rejected' and result.returncode == 0):
        raise RuntimeError('PACKAGE_COMMAND_RESULT_UNEXPECTED')
    return result.returncode


def native_info(binary):
    return json.loads(subprocess.check_output([str(binary), '--package-info'], text=True, timeout=30))


def setup(release, target, expected=0):
    manifest = json.loads((release / 'release.json').read_text(encoding='utf-8'))
    installer = release / manifest['installer']
    # NSIS /D must be the final unquoted argument, including spaces in its value.
    return run(f'"{installer}" /S /D={target}', expected=expected, timeout=240)


def uninstall(target):
    candidates = list(target.glob('*uninstall*.exe')) + list(target.glob('*Uninstall*.exe'))
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) != 1:
        raise RuntimeError('OWNED_UNINSTALLER_NOT_UNIQUE')
    run([str(candidates[0]), '/S'], timeout=180)
    deadline = time.monotonic() + 30
    while target.exists() and time.monotonic() < deadline:
        time.sleep(.1)
    if target.exists():
        raise RuntimeError('INSTALL_DIRECTORY_NOT_REMOVED')


def sessions(host, device):
    with closing(sqlite3.connect(host.host_root / 'private/devices.sqlite3')) as database:
        return frozenset(v[0] for v in database.execute('SELECT digest FROM device_sessions WHERE device_id=?', (device,)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--delivery', choices=['manager', 'sales'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=1)
    args = parser.parse_args()
    if os.name != 'nt':
        raise RuntimeError('ACTUAL_WINDOWS_REQUIRED')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'task': 'P07-04', 'delivery': args.delivery, 'status': 'running', 'production_paths_accessed': False,
              'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'checks': [], 'runner_elevated': bool(ctypes.windll.shell32.IsUserAnAdmin()),
              'non_admin_user_acceptance': 'pending if CI runner is elevated', 'full_installed_business_UI_acceptance': 'pending user observation'}
    save = lambda: (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    node = shutil.which('node')
    package = ROOT / 'desktop/tools/package.mjs'
    deployment = ROOT / 'desktop/tools/deployment.mjs'
    host = None
    installed = None
    process = None
    try:
        host = Hosted(font=str(ROOT / 'desktop/public/fonts/NotoSansSC-VF.ttf'))
        cleanup_profile = host.root / 'desktop'
        cleanup_profile.mkdir()
        (cleanup_profile / '777-isolated-profile.json').write_text('{"production":false}', encoding='utf-8')
        enable(host)
        connection = {'url': f'https://127.0.0.1:{host.port}', 'certificate_pem': (host.host_root / 'service-cert.pem').read_text(encoding='utf-8'), 'certificate_sha256': host.config['certificate_sha256']}
        config = host.root / 'public-connection.json'
        config.write_text(json.dumps({'schema': '777-public-connection-v1', 'connection': connection}), encoding='utf-8')
        version = json.loads((ROOT / 'desktop/src-tauri/tauri.conf.json').read_text())['version']
        parts = [int(v) for v in version.split('.')]
        upgrade_version = '.'.join(map(str, [parts[0], parts[1], parts[2] + 1]))
        releases = []
        env = dict(os.environ, CARGO_BUILD_JOBS=str(args.jobs))
        for tag, number in [('initial', version), ('upgrade', upgrade_version)]:
            release = output / tag
            save()
            if tag == 'initial':
                from p07_developer_package_check import package_from_window
                package_from_window(host, ROOT, args.delivery, number, release)
                report['checks'].append('P07_05_actual_developer_UI_button_built_role_NSIS_package')
            else:
                run([node, str(package), '--delivery', args.delivery, '--connection', str(config), '--output', str(release), '--version', number], env=env)
            run([node, str(deployment), 'verify', '--release', str(release)])
            releases.append(release)
        initial, upgrade = releases
        binary_name = f'quote777-{args.delivery}.exe'
        expected = json.loads((initial / 'release.json').read_text(encoding='utf-8'))
        report['checks'].append('two_real_role_locked_NSIS_packages_and_manifests_built')
        report['package_versions'] = [version, upgrade_version]
        # Prove another role's directory is rejected without overwriting its marker.
        conflict = host.root / 'other-role-install'
        conflict.mkdir()
        marker = conflict / 'quote777-install.ini'
        other = 'sales' if args.delivery == 'manager' else 'manager'
        marker.write_text(f'[release]\ndelivery={other}\n', encoding='utf-8')
        setup(initial, conflict, expected='rejected')
        assert not (conflict / binary_name).exists() and f'delivery={other}' in marker.read_text()
        report['checks'].append('cross_role_install_directory_rejected')
        installed = host.root / '中文 安装目录'
        setup(initial, installed)
        assert native_info(installed / binary_name)['version'] == version
        local = host.root / 'local-app-data'
        profile = local / 'cn.uniqueness.quote777' / args.delivery
        process_env = dict(os.environ, LOCALAPPDATA=str(local))
        account = next(v for v in host.client('manager').request('GET', '/v1/accounts')['accounts'] if v['username'] == ('manager' if args.delivery == 'manager' else 'sales-one'))
        grant = host.client('manager').request('POST', '/v1/device-grants', {'subject': account['id'], 'delivery': args.delivery, 'ttl_seconds': 600})
        grant_file = host.root / 'one-device-grant.json'
        grant_file.write_text(json.dumps({'schema': '777-desktop-bootstrap-v1', 'delivery': args.delivery, 'connection': connection, 'ticket': grant['ticket']}), encoding='utf-8')
        run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(initial / 'enroll.ps1'),
             '-ReleaseDirectory', str(initial), '-GrantFile', str(grant_file)], env=process_env)

        def open_and_close(stage, device=None):
            nonlocal process
            before = sessions(host, device) if device else frozenset()
            log = (output / f'{stage}-process.log').open('wb')
            try:
                process = subprocess.Popen([str(installed / binary_name)], env=process_env, stdout=log, stderr=subprocess.STDOUT)
                deadline = time.monotonic() + 45
                current = device
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError('INSTALLED_APP_EXITED_BEFORE_AUTHENTICATION')
                    if current is None:
                        with closing(sqlite3.connect(host.host_root / 'private/devices.sqlite3')) as db:
                            current = db.execute('SELECT device_id FROM grants WHERE digest=?', (hashlib.sha256(grant['ticket'].encode()).hexdigest(),)).fetchone()[0]
                    if current and sessions(host, current) and sessions(host, current) != before and not (profile / 'bootstrap.json').exists():
                        break
                    time.sleep(.1)
                else:
                    raise RuntimeError('INSTALLED_NATIVE_AUTOMATIC_SESSION_TIMEOUT')
                result = close_window(process, expected['product_name'], output / f'{stage}-close.json', windows=Windows())
                process = None
                report['checks'].append(stage + '_real_installed_native_auth_and_natural_close')
                return current, result
            finally:
                log.close()

        device, first_close = open_and_close('first-install')
        assert (profile / 'device.bin').is_file()
        identity_bytes = (profile / 'device.bin').read_bytes()
        retained = profile / 'webview2' / 'package-retention-probe.txt'
        retained.parent.mkdir(exist_ok=True)
        retained.write_text('owned lifecycle probe, not a financial request', encoding='utf-8')
        setup(upgrade, installed)
        assert native_info(installed / binary_name)['version'] == upgrade_version
        assert (profile / 'device.bin').read_bytes() == identity_bytes and retained.is_file()
        _, upgrade_close = open_and_close('upgrade', device)
        setup(initial, installed, expected='rejected')
        assert native_info(installed / binary_name)['version'] == upgrade_version
        report['checks'].append('unreviewed_direct_downgrade_rejected')
        run([node, str(deployment), 'check-rollback', '--current', str(upgrade), '--previous', str(initial)])
        uninstall(installed)
        assert (profile / 'device.bin').read_bytes() == identity_bytes and retained.is_file()
        setup(initial, installed)
        assert native_info(installed / binary_name)['version'] == version
        _, rollback_close = open_and_close('compatible-rollback', device)
        uninstall(installed)
        assert (profile / 'device.bin').read_bytes() == identity_bytes and retained.is_file()
        report['checks'].append('upgrade_uninstall_and_controlled_rollback_preserve_DPAPI_identity_and_webview_directory')
        report['close'] = {'initial': first_close, 'upgrade': upgrade_close, 'rollback': rollback_close}
        report['status'] = 'actual_Windows_installer_lifecycle_and_native_auth_passed_user_acceptance_pending'
    except BaseException as error:
        report['status'] = 'failed'
        report['error'] = type(error).__name__ + ': ' + str(error)
        traceback.print_exc()
        raise
    finally:
        # No force close can produce a passing lifecycle result.
        if process is not None and process.poll() is None:
            report['failed_app_pid'] = process.pid
            report['sandbox_cleanup'] = 'blocked by failed owned app; retained for diagnosis'
        elif host is not None:
            try:
                scenario = SimpleNamespace(host=host, profile=host.root / 'desktop', close=host.close)
                report['sandbox_cleanup'] = cleanup_webview_sandbox(scenario, output / 'cleanup.json')
                report['sandbox_cleaned'] = True
            except BaseException as error:
                report['status'] = 'failed'
                report['cleanup_error'] = type(error).__name__ + ': ' + str(error)
                save()
                raise
        save()
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
