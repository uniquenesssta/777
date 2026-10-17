"""Create a new production host using the existing native init and daily backup contracts."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from . import native
from .inventory import collect
from .policy import FORMAT, HOST_ORDER, local_root, require_primary


def write_new(path, value):
    import os
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8-sig')) == value:
            return
        raise ValueError('EXISTING_DEPLOYMENT_FILE_CONFLICT')
    with open(path, 'x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def prepare(root, backup, hidden, user, secret, *, address=HOST_ORDER[0], port=8477, hour=23, skip_build=False, resume=False):
    site = collect()
    require_primary(address, site['addresses'])
    root = local_root(root, new=not resume)
    if not 1 <= port <= 65535 or not 0 <= hour <= 23:
        raise ValueError('DEPLOYMENT_PORT_OR_HOUR_INVALID')
    # Fail before creating a host when credentials or locations were omitted.
    if not user.strip() or not secret or not str(backup).strip() or not str(hidden).strip():
        raise ValueError('DEPLOYMENT_INPUT_REQUIRED')
    previous = root / 'private/deployment.json'
    saved = None
    if previous.exists():
        from .policy import manifest
        _, saved = manifest(root)
        if saved['owner_sid'] != site['sid']:
            raise ValueError('DEPLOYMENT_OWNER_CONFLICT')
        for name, field in [('rust-service-host.exe', 'host_sha256'), ('host-run.ps1', 'runner_sha256'), ('host-identity.ps1', 'identity_sha256')]:
            if hashlib.sha256((root / 'private' / name).read_bytes()).hexdigest() != saved[field]:
                raise ValueError('HOST_DEPLOYMENT_RESOURCE_CHANGED')
    backup, hidden = Path(backup), Path(hidden)
    if not backup.is_absolute() or not hidden.is_absolute():
        raise ValueError('ABSOLUTE_BACKUP_DIRECTORIES_REQUIRED')
    for location in (backup, hidden):
        # Deployment resources and mutable business/backup files must not overlap.
        location = Path(location).resolve(strict=False)
        if root == location or root in location.parents or location in root.parents:
            raise ValueError('HOST_ROOT_AND_BACKUPS_MUST_BE_SEPARATE')
    if resume:
        native.call(root / 'private/rust-service-host.exe', ['authorize', '--root', root, '--admin', user], secret)
        probe = native.call(root / 'private/rust-service-host.exe', ['inspect', '--root', root])
        if probe.get('shutdown_control') != 'stdin-v1':
            raise ValueError('HOST_RESOURCE_UPGRADE_REQUIRED_FOR_DEPLOYMENT')
        config = json.loads((root / 'private/service.json').read_text(encoding='utf-8'))
        if config['bind'] != address or config['port'] != port:
            raise ValueError('EXISTING_HOST_ENDPOINT_CONFLICT')
    else:
        original, worker = native.resources(skip_build)
        native.call(original, ['init', '--root', root, '--backup-dir', backup,
                    '--host', address, '--host', '127.0.0.1', '--host', 'localhost',
                    '--bind', address, '--port', port, '--admin', user, '--worker', worker,
                    '--notices', native.ROOT / 'THIRD_PARTY_NOTICES.md'], secret)
    host = root / 'private/rust-service-host.exe'
    # A later error leaves the native host stopped for diagnosis; never recreate/erase it.
    native.call(host, ['enable-devices', '--root', root, '--admin', user], secret)
    native.call(host, ['configure-daily', '--root', root, '--backup-dir', backup,
                '--hidden-dir', hidden, '--daily-hour', hour, '--admin', user], secret)
    checked = native.call(host, ['inspect', '--root', root])
    if checked.get('shutdown_control') != 'stdin-v1':
        raise ValueError('HOST_RESOURCE_UPGRADE_REQUIRED_FOR_DEPLOYMENT')
    template = json.loads((root / 'client-template.json').read_text(encoding='utf-8'))
    public = {'schema': '777-public-connection-v1', 'connection': {
        'url': template['url'], 'certificate_pem': (root / 'service-cert.pem').read_text(encoding='utf-8'),
        'certificate_sha256': template['certificate_sha256']}}
    write_new(root / 'connection.json', public)
    runner = root / 'private/host-run.ps1'
    identity = root / 'private/host-identity.ps1'
    for target in (runner, identity):
        original = native.ROOT / 'deployment/windows' / target.name
        if target.exists() and target.read_bytes() != original.read_bytes():
            raise ValueError('EXISTING_HOST_RUNNER_CHANGED_REVIEW_REQUIRED')
        if not target.exists():
            shutil.copyfile(original, target)
    if saved is not None:
        source = saved['source_commit']
    else:
        # A resumed external native host has verified resources but unknown build provenance.
        source = None if resume else subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=native.ROOT, text=True).strip()
    deployment = {'schema': FORMAT, 'root': str(root), 'owner_sid': site['sid'], 'owner_account': site['account'],
        'machine': site['machine'], 'source_commit': source, 'host_order': list(HOST_ORDER),
        'active_address': address, 'port': port, 'ledger_id': checked['inventory']['ledger_id'],
        'certificate_sha256': checked['certificate_sha256'], 'autostart': 'not_registered',
        'replication': 'not_implemented_standby_must_not_write',
        'host_sha256': hashlib.sha256(host.read_bytes()).hexdigest(),
        'identity_sha256': hashlib.sha256(identity.read_bytes()).hexdigest(),
        'runner_sha256': hashlib.sha256(runner.read_bytes()).hexdigest()}
    write_new(root / 'private/deployment.json', deployment)
    return {'status': 'prepared_stopped', 'root': str(root), 'source_commit': source,
            'ledger_id': deployment['ledger_id'], 'public_connection': str(root / 'connection.json'),
            'autostart': 'not_registered', 'replication': deployment['replication']}
