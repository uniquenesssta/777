"""Delete only recorded/generated package output, never an arbitrary output root."""
import json
import os
import re
import shutil
import stat
import uuid
from pathlib import Path


def read_json(path):
    if path.stat().st_size > 2 * 1024 * 1024:
        raise RuntimeError('PACKAGE_CLEANUP_UNSAFE')
    return json.loads(path.read_text(encoding='utf-8'))


def safe_tree(path):
    for part in [path, *path.parents]:
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise RuntimeError('PACKAGE_CLEANUP_UNSAFE')
    if path.is_dir():
        for base, dirs, files in os.walk(path, followlinks=False):
            if {'ledger.sqlite3', 'service.json', 'host-local.json'} & set(files):
                raise RuntimeError('PACKAGE_CLEANUP_UNSAFE')
            for name in dirs + files:
                child = Path(base) / name
                info = child.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise RuntimeError('PACKAGE_CLEANUP_UNSAFE')


def registry(owner):
    path = owner.dev.DEV / 'package-outputs.json'
    if not path.exists():
        return []
    safe_tree(path)
    data = read_json(path)
    if data.get('schema') != '777-package-outputs-v1' or not isinstance(data.get('outputs'), list):
        raise RuntimeError('PACKAGE_CLEANUP_UNSAFE')
    return data['outputs']


def remember_output(owner, job):
    from p07_developer import replace_json
    rows = registry(owner)
    row = {key: job[key] for key in ['id', 'output', 'delivery', 'version']}
    rows = [old for old in rows if old['id'] != row['id']] + [row]
    replace_json(owner.dev.DEV / 'package-outputs.json', {'schema': '777-package-outputs-v1', 'outputs': rows})


def plan(owner):
    rows = registry(owner)
    if owner.job:
        rows.append({key: owner.job[key] for key in ['id', 'output', 'delivery', 'version']})
    issuance = owner.dev.DEV / 'local-issuance'
    if issuance.exists():
        safe_tree_shallow(issuance)
        for stage in issuance.glob('*.bin.stage'):
            safe_tree_shallow(stage)
            state = stage / 'build-state.json'
            if state.is_file():
                safe_tree(state)
                value = read_json(state)
                if stage.name == str(value.get('package_id')) + '.bin.stage':
                    rows.append(dict(id=value.get('package_id'), output=value.get('output'), delivery=value.get('delivery'), version=value.get('version')))
    roots = {Path(owner.preferences['output']), owner.dev.DEV / 'packages'} | {Path(row['output']).parent for row in rows}
    for root in roots:
        if not root.exists():
            continue
        safe_tree_shallow(root)
        for child in root.iterdir():
            if not re.fullmatch(r'(manager|sales)-\d+\.\d+\.\d+-[0-9a-f]{8}', child.name):
                continue
            safe_tree_shallow(child)
            manifest = child / 'release.json'
            if manifest.is_file():
                safe_tree(manifest)
                value = read_json(manifest)
                if value.get('schema') == '777-desktop-release-v1':
                    rows.append(dict(id=value.get('package_id'), output=str(child), delivery=value.get('delivery'), version=value.get('version')))
    found = {}
    for row in rows:
        key = str(uuid.UUID(row['id']))
        path = Path(row['output'])
        if row['delivery'] not in ['manager', 'sales'] or not re.fullmatch(r'\d+\.\d+\.\d+', row['version']) or not path.is_absolute() or path.name != f"{row['delivery']}-{row['version']}-{key[:8]}":
            raise RuntimeError('PACKAGE_CLEANUP_UNSAFE')
        for artifact in artifacts(owner, row):
            if artifact.exists() or artifact.is_symlink():
                safe_tree(artifact)
        found[str(path)] = dict(id=key, output=str(path), delivery=row['delivery'], version=row['version'])
    return list(found.values())


def safe_tree_shallow(path):
    for part in [path, *path.parents]:
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise RuntimeError('PACKAGE_CLEANUP_UNSAFE')


def artifacts(owner, row):
    key = row['id']
    return [Path(row['output']), owner.dev.DEV / 'local-issuance' / (key + '.bin'),
            owner.dev.DEV / 'local-issuance' / (key + '.bin.stage'),
            owner.dev.ROOT / 'target' / 'packages' / row['delivery'] / 'resources' / key]


def cleanup(owner, execute=False):
    from p07_developer import replace_json
    with owner.job_lock:
        if (owner.worker and owner.worker.is_alive()) or (owner.job and owner.job['state'] in ['running', 'cancelling']):
            raise RuntimeError('PACKAGE_CLEANUP_BUSY')
        rows = plan(owner)
        if not execute:
            return {'count': len(rows), 'outputs': [row['output'] for row in rows]}
        # Preflight every tree before removing any output. Never remove the parent directory.
        paths = {path for row in rows for path in artifacts(owner, row) if path.exists() or path.is_symlink()}
        for path in paths:
            safe_tree(path)
        for path in paths:
            if path.is_dir(): shutil.rmtree(path)
            else: path.unlink()
        replace_json(owner.dev.DEV / 'package-outputs.json', {'schema': '777-package-outputs-v1', 'outputs': []})
        owner.job = None
        (owner.dev.DEV / 'automatic-job.json').unlink(missing_ok=True)
    return {**owner.package_status(), 'cleaned': len(rows)}
