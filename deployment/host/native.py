"""Build real host resources and invoke the existing operator CLI without exposing passwords."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def call(executable, args, secret=None):
    command = [str(executable), *map(str, args)]
    if secret is not None:
        command.append('--secret-stdin')
    result = subprocess.run(command, input=None if secret is None else json.dumps({'password': secret}).encode(),
                            capture_output=True, timeout=180, env={**os.environ, 'QUOTE777_LOG_ROOT': str(ROOT)})
    # Native stderr can contain machine paths; only expose the stable operator error code.
    if result.returncode:
        lines = result.stderr.decode('utf-8', 'replace').splitlines()
        code = 'NATIVE_HOST_OPERATION_FAILED'
        for line in reversed(lines):
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    continue
                candidate = value.get('error') or value.get('code')
                if isinstance(candidate, str) and candidate.replace('_', '').isalnum():
                    code = candidate
                    break
            except (ValueError, TypeError):
                pass
        raise ValueError(code)
    return json.loads(result.stdout.decode('utf-8-sig').splitlines()[-1])


def resources(skip_build=False):
    if os.name != 'nt':
        raise ValueError('WINDOWS_DEPLOYMENT_REQUIRED')
    if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT, text=True).strip():
        raise ValueError('CLEAN_SOURCE_REQUIRED_FOR_HOST_RESOURCES')
    if not skip_build:
        jobs = max(1, min(12, os.cpu_count() or 1))
        print(f'准备实际后台程序（{jobs}个构建任务；不构建母子安装包）…', flush=True)
        subprocess.run(['cargo', 'build', '--locked', '--release', '-p', 'quote-host', '-p', 'quote-ledger', '-j', str(jobs)],
                       cwd=ROOT, check=True)
    host, worker = (ROOT / 'target/release' / name for name in ('quote-host.exe', 'quote-ledger.exe'))
    for path in (host, worker):
        with path.open('rb') as stream:
            if stream.read(2) != b'MZ':
                raise ValueError('WINDOWS_HOST_RESOURCE_REQUIRED')
    return host, worker
