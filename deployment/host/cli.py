"""Small operator entry; inventory is read-only and preparation never installs startup implicitly."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import subprocess
from .inventory import collect
from .policy import manifest
from .prepare import prepare
from .native import ROOT


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', nargs='?', choices=['inventory', 'prepare', 'configure', 'install', 'status', 'start', 'stop', 'remove'], default='inventory')
    parser.add_argument('--root', type=Path)
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--hidden', type=Path)
    parser.add_argument('--address', help='Local IPv4 address; required when multiple LAN interfaces exist')
    parser.add_argument('--port', type=int, default=8477)
    parser.add_argument('--hour', type=int, default=23)
    parser.add_argument('--admin', default='manager')
    parser.add_argument('--skip-build', action='store_true')
    args = parser.parse_args(argv)
    if os.name != 'nt':
        print('此入口需要在实际 Windows 服务主机运行；未修改任何主机。')
        return 2
    import sys
    sys.path.insert(0, str(ROOT / 'tools'))
    import p07_diagnostics as diagnostics
    diagnostics.initialize(ROOT)
    diagnostics.event('deployment.operation.start', operation=args.operation)
    try:
        if args.operation == 'inventory':
            value = collect()
            diagnostics.event('deployment.inventory', machine=value['machine'], os=value['os'],
                              addresses=value['addresses'], account=value['account'], sid=value['sid'])
        elif args.operation in ('prepare', 'configure'):
            if not all([args.root, args.backup, args.hidden]):
                raise ValueError('prepare需要--root、--backup、--hidden，使用独立的新主机目录')
            secret = getpass.getpass('后台访问密码（12～128字符，不显示、不保存到命令或报告）：')
            if secret != getpass.getpass('再次输入密码：'):
                raise ValueError('PASSWORD_CONFIRMATION_MISMATCH')
            value = prepare(args.root, args.backup, args.hidden, args.admin, secret,
                            address=args.address, port=args.port, hour=args.hour, skip_build=args.skip_build,
                            resume=args.operation == 'configure')
            del secret
        else:
            if not args.root:
                raise ValueError('--root必须指向已准备的本机服务目录')
            root, _ = manifest(args.root)
            # Windows task credentials are entered inside PowerShell; never placed in arguments.
            result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                str(ROOT / 'deployment/windows/host-task.ps1'), '-Operation', args.operation, '-Root', str(root)], stderr=subprocess.PIPE)
            if result.returncode:
                stderr = result.stderr.decode('utf-8', 'replace')
                print(stderr, file=sys.stderr)
                for line in stderr.splitlines():
                    try:
                        failure = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(failure, dict):
                        continue
                    code = failure.get('error', '')
                    diagnostics.event('deployment.task.failed', operation=args.operation, exit_code=result.returncode,
                                      error=code if isinstance(code, str) and re.fullmatch(r'[A-Z][A-Z0-9_]{4,100}', code) else 'WINDOWS_TASK_PROVIDER_ERROR',
                                      hresult=failure.get('hresult'), error_type=failure.get('error_type'))
                raise ValueError('HOST_TASK_OPERATION_FAILED: 请查看当前控制台和运行日志')
            value = {'status': 'task_operation_completed', 'operation': args.operation}
        diagnostics.event('deployment.operation.finish', operation=args.operation, status=value.get('status', 'inventory_collected'))
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        diagnostics.failure(args.operation, exc)
        code = str(exc).split(':', 1)[0]
        diagnostics.event('deployment.operation.failed', operation=args.operation, error_type=type(exc).__name__)
        if re.fullmatch(r'[A-Z][A-Z0-9_]{4,100}', code):
            diagnostics.event('deployment.failure.code', operation=args.operation, error=code)
        print(f'部署未完成：{exc}。已有目录保留；不要删除账本后重试。')
        return 2
