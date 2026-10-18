"""Source-to-working-copy orchestration; source directories are never reconfigured."""
import json
import uuid
from pathlib import Path


def import_directory(controller, source, target, username, password):
    from p07_developer import local, replace_json
    source, target = local(source, directory=True), local(target)
    if target == source or source in target.parents:
        raise RuntimeError('OFFLINE_TARGET_INSIDE_SOURCE')
    if not username or not password:
        raise RuntimeError('DEVELOPER_CREDENTIAL_REQUIRED')
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise RuntimeError('RESTORE_REQUIRES_NEW_DIRECTORY')
    local(target.parent, directory=True)
    package = target.parent / ('.777-offline-' + uuid.uuid4().hex + '.qbackup')
    try:
        controller.dev.command(['export-offline', '--root', str(source), '--package', str(package), '--admin', username], password)
        record = dict(kind='offline_directory', original=str(source), working_copy=str(target))
        record_file = controller.dev.DEV / 'data-source.json'
        previous = json.loads(record_file.read_text(encoding='utf-8')) if record_file.exists() else None
        replace_json(record_file, record)
        try:
            return controller.restore_data(str(package), str(target))
        except BaseException:
            if previous is None:
                record_file.unlink(missing_ok=True)
            else:
                replace_json(record_file, previous)
            raise
    finally:
        package.unlink(missing_ok=True)


def source_status(controller):
    path = controller.dev.DEV / 'data-source.json'
    if not path.exists():
        return None
    if path.stat().st_size > 65536:
        raise RuntimeError('DEVELOPER_CONFIG_INVALID')
    value = json.loads(path.read_text(encoding='utf-8'))
    return value if Path(value['working_copy']) == controller.root else None
