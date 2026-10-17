"""Local deployment ownership and currently supported activation policy."""
import os
from pathlib import Path

HOST_ORDER = ('192.168.4.23', '192.168.4.38')
FORMAT = '777-site-deployment-v1'


def require_primary(address, local_addresses):
    if address not in HOST_ORDER:
        raise ValueError('DEPLOYMENT_HOST_NOT_IN_PLAN')
    if address not in local_addresses:
        raise ValueError('DEPLOYMENT_MUST_RUN_ON_SELECTED_HOST')
    if address != HOST_ORDER[0]:
        raise ValueError('STANDBY_REPLICATION_NOT_IMPLEMENTED: 4.38 cannot be initialized as an independent writer')


def local_root(value, *, new=False):
    path = Path(value)
    if not path.is_absolute() or any(c in str(path) for c in '\r\n"'):
        raise ValueError('ABSOLUTE_HOST_ROOT_REQUIRED')
    if os.name == 'nt':
        import ctypes
        if str(path).startswith('\\\\') or ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) == 4:
            raise ValueError('HOST_DATABASE_REQUIRES_LOCAL_DISK')
    for item in [path, *path.parents]:
        if item.exists() and (item.is_symlink() or getattr(item.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('DEPLOYMENT_ROOT_REPARSE_POINT')
    if new and (path.exists() or not path.parent.is_dir()):
        raise ValueError('NEW_HOST_ROOT_WITH_EXISTING_PARENT_REQUIRED')
    return path


def manifest(root):
    import json
    root = local_root(root)
    path = root / 'private/deployment.json'
    if path.stat().st_size > 65536:
        raise ValueError('DEPLOYMENT_MANIFEST_TOO_LARGE')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if value.get('schema') != FORMAT or Path(value['root']) != root:
        raise ValueError('DEPLOYMENT_IDENTITY_CONFLICT')
    return root, value
