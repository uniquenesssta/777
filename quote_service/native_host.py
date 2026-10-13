"""Registered native host resources, for legacy maintenance/verification only."""
from .protocol import APIError
from quote_ledger.paths import local_path
from .rust_ledger import file_hash
HOST_FILES={'rust-service-host.exe','rust-host-notices.txt'}
def validate_resources(private,config):
    backend=config.get('service_backend','python')
    if backend not in {'python','rust'}:raise APIError(422,'HOST_BACKEND_INVALID')
    expected=config.get('rust_host_sha256')
    if expected is not None:
        if type(expected) is not str or len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected):raise APIError(422,'HOST_RESOURCE_IDENTITY_CONFLICT')
        local_path(private/'rust-host-notices.txt')
        if file_hash(local_path(private/'rust-service-host.exe'))!=expected:raise APIError(503,'HOST_RESOURCE_IDENTITY_CONFLICT')
    if backend=='rust' and (expected is None or config.get('ledger_backend')!='rust'):raise APIError(422,'HOST_BACKEND_INVALID')
