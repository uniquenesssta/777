"""Explicit host-only allowlist; never copy a working tree, database or credentials."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

SCHEMA = '777-host-bundle-v1'
ENTRY_POINTS = ('host.ps1', 'host-console.ps1', 'host-defaults.json', 'collect.cmd', 'manage.cmd', 'setup.cmd', 'check.cmd')
PORTABLE = ENTRY_POINTS + ('host-log.ps1', 'host-package.ps1', 'host-site.ps1', 'host-paths.ps1', 'host-native.ps1',
                           'host-prepare.ps1', 'host-access.ps1', 'host-settings.ps1', 'host-options.ps1', 'host-setup.ps1', 'host-visibility.ps1', 'host-check.ps1', 'HostProbe.cs',
                           'host-cluster-files.ps1', 'host-cluster-primary.ps1', 'host-cluster-join.ps1')
LIFECYCLE = ('host-identity.ps1', 'host-run.ps1', 'host-task.ps1')


def assemble(source: Path, output: Path, host: Path, worker: Path, commit: str):
    if output.exists() or not output.is_absolute():
        raise ValueError('NEW_ABSOLUTE_BUNDLE_OUTPUT_REQUIRED')
    for executable in (host, worker):
        with executable.open('rb') as stream:
            if stream.read(2) != b'MZ':
                raise ValueError('WINDOWS_HOST_RESOURCE_REQUIRED')
    output.mkdir(parents=True, exist_ok=False)
    stage = output / 'Quote777Host'
    stage.mkdir()
    files = {'bin/quote-host.exe': host, 'bin/quote-ledger.exe': worker,
             'THIRD_PARTY_NOTICES.md': source / 'THIRD_PARTY_NOTICES.md',
             'README.txt': source / 'deployment/bundle/README.txt'}
    for name in PORTABLE:
        files[name if name in ENTRY_POINTS else 'scripts/' + name] = source / 'deployment/windows/portable' / name
    for name in LIFECYCLE:
        files['scripts/' + name] = source / 'deployment/windows' / name
    for relative, origin in files.items():
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, destination)
    manifest = {'schema': SCHEMA, 'source_commit': commit, 'created_at': datetime.now(timezone.utc).isoformat(),
                'platform': 'windows-x86_64', 'deployment_mode': 'standalone',
                'replication': 'primary_async_snapshot_v1',
                'files': {name: hashlib.sha256((stage / name).read_bytes()).hexdigest() for name in sorted(files)}}
    (stage / 'host-package.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    archive = output / 'Quote777Host.zip'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as zipped:
        for file in sorted(stage.rglob('*')):
            if file.is_file():
                zipped.write(file, file.relative_to(output).as_posix())
    return {'status': 'host_bundle_created', 'source_commit': commit, 'archive': str(archive),
            'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'files': len(files) + 1,
            'server_requirements': 'Windows PowerShell 5.1; no developer app, Git, Node, Python or Rust SDK',
            'replication': manifest['replication']}
