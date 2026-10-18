"""Run on the developer's Windows machine, never on service hosts."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from ..host import native
from .archive import assemble


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--skip-build', action='store_true')
    args = parser.parse_args(argv)
    if os.name != 'nt':
        print('后台出包需要在开发用 Windows 电脑执行；服务电脑使用包内 host.ps1。')
        return 2
    sys.path.insert(0, str(native.ROOT / 'tools'))
    import p07_diagnostics as diagnostics
    diagnostics.initialize(native.ROOT)
    try:
        diagnostics.event('host.bundle.start')
        host, worker = native.resources(args.skip_build)
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=native.ROOT, text=True).strip()
        output = args.output or native.ROOT / 'reports/host-packages' / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + commit[:8])
        result = assemble(native.ROOT, output, host, worker, commit)
        diagnostics.event('host.bundle.complete', archive=result['archive'], sha256=result['sha256'], source_commit=commit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        diagnostics.failure('host.bundle', exc)
        print(f'后台出包未完成：{exc}')
        return 2
