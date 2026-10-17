"""Windows path integration in owned temporary shares; never opens the user's mapped disks."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]


def powershell(script, env):
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                             "$ErrorActionPreference='Stop'; " + script],
                            env=env, capture_output=True, text=True, encoding='utf-8', timeout=60)
    if result.returncode:raise RuntimeError(result.stderr[-3000:])
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if os.name != 'nt':raise RuntimeError('WINDOWS_PATH_INTEGRATION_REQUIRED')
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(task='P07-06 selectable folders', status='running', production_paths_accessed=False,
                  source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip())
    with tempfile.TemporaryDirectory(prefix='777-paths-') as owned:
        base = Path(owned).resolve()
        share = '777-check-' + uuid.uuid4().hex[:12]
        env = dict(os.environ, QUOTE777_TEST_SHARE=share, QUOTE777_TEST_ROOT=str(base))
        mapped = False
        try:
            drive = powershell("$d = 90..82 | ForEach-Object { [char]$_ } | Where-Object { -not (Test-Path ($_ + ':\\')) } | Select-Object -First 1; if (-not $d) { throw 'NO_FREE_TEST_DRIVE' }; Write-Output ($d + ':')", env)
            env['QUOTE777_TEST_DRIVE'] = drive
            powershell("$user=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name; New-SmbShare -Name $env:QUOTE777_TEST_SHARE -Path $env:QUOTE777_TEST_ROOT -FullAccess $user | Out-Null; New-SmbShare -Name ($env:QUOTE777_TEST_SHARE + '-ro') -Path $env:QUOTE777_TEST_ROOT -ReadAccess $user | Out-Null", env)
            powershell("& net.exe use $env:QUOTE777_TEST_DRIVE ('\\\\localhost\\' + $env:QUOTE777_TEST_SHARE) /persistent:no; if ($LASTEXITCODE -ne 0) { throw 'TEST_MAPPING_FAILED' }", env)
            mapped = True
            report['mapping'] = dict(drive=drive, share='\\\\localhost\\' + share)
            readonly = '\\\\localhost\\' + share + '-ro'
            # One full run traverses both mapped and canonical UNC identities, including restart/recovery.
            subprocess.run([sys.executable, str(ROOT / 'tools/p07_developer_check.py'),
                            '--workspace', drive + '\\', '--readonly-destination', readonly,
                            '--output', str(args.output / 'shared')], check=True, cwd=ROOT, timeout=600)
            # A selected directory junction must also work through the controller and native CLI.
            actual = base / 'junction-target'; actual.mkdir()
            junction = base / 'selected-junction'
            env.update(QUOTE777_TEST_JUNCTION=str(junction), QUOTE777_TEST_TARGET=str(actual))
            powershell("New-Item -ItemType Junction -Path $env:QUOTE777_TEST_JUNCTION -Target $env:QUOTE777_TEST_TARGET | Out-Null", env)
            try:
                subprocess.run([sys.executable, str(ROOT / 'tools/p07_developer_check.py'),
                                '--workspace', str(junction), '--output', str(args.output / 'junction')],
                               check=True, cwd=ROOT, timeout=600)
            finally:junction.rmdir()
            report['status'] = 'passed'
        except BaseException as error:
            report['status'] = 'failed'; report['error'] = type(error).__name__ + ': ' + str(error)
            raise
        finally:
            try:
                if mapped:powershell("& net.exe use $env:QUOTE777_TEST_DRIVE /delete /y; if ($LASTEXITCODE -ne 0) { throw 'TEST_MAPPING_CLEANUP_FAILED' }", env)
                powershell("foreach ($n in @($env:QUOTE777_TEST_SHARE, ($env:QUOTE777_TEST_SHARE + '-ro'))) { if (Get-SmbShare -Name $n -ErrorAction SilentlyContinue) { Remove-SmbShare -Name $n -Force } }", env)
                report['owned_share_cleanup'] = True
            finally:
                (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':main()
