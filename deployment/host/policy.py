"""Local deployment ownership and currently supported activation policy."""
import os
from pathlib import Path

HOST_ORDER = ('192.168.4.23', '192.168.4.38')
FORMAT = '777-site-deployment-v1'


def require_local_host(address, local_addresses):
    import ipaddress
    try:
        value = ipaddress.IPv4Address(address)
    except (ipaddress.AddressValueError, TypeError):
        raise ValueError('LOCAL_HOST_IPV4_REQUIRED') from None
    if value.is_unspecified or value.is_loopback or value.is_multicast or value.is_link_local or int(value) >= 0xE0000000:
        raise ValueError('LOCAL_HOST_IPV4_REQUIRED')
    if address not in local_addresses:
        raise ValueError('DEPLOYMENT_MUST_RUN_ON_SELECTED_HOST')


def choose_local_address(address, local_addresses):
    if address:
        require_local_host(address, local_addresses)
        return address
    eligible = []
    for candidate in sorted(set(local_addresses)):
        try:
            require_local_host(candidate, local_addresses)
            eligible.append(candidate)
        except ValueError:
            pass
    if len(eligible) != 1:
        raise ValueError('LOCAL_HOST_ADDRESS_SELECTION_REQUIRED')
    return eligible[0]


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
    # Windows may provide an 8.3 alias for the parent (notably TEMP). Compare
    # both the host root and backup destinations in the same canonical form.
    return path.resolve(strict=False)


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
