"""Focused offline-source checks inside the developer runner's owned synthetic workspace."""
import hashlib
import json
import os
from pathlib import Path


def tree(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def check(controller, ipc, source, original, target, expected_ledger, expected_order, readonly=None):
    # A live source must be rejected without stopping it or changing the active selection.
    try:
        ipc('developer', request=dict(op='import_directory', root=str(original), target=str(target), username=controller.user, password=controller.password))
    except RuntimeError as error:
        assert 'SERVICE_OWNER_BUSY' in str(error), error
    else:
        raise AssertionError('LIVE_SOURCE_ACCEPTED')
    assert controller.root == original and not target.exists()
    credentials=controller.credentials[str(source)]
    config_file=source/'private/service.json'
    config=json.loads(config_file.read_text(encoding='utf-8'))
    config['bind']='0.0.0.0'  # Owned fixture now has a formal/non-loopback host configuration.
    config_file.write_text(json.dumps(config),encoding='utf-8')
    attrs=None
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.GetFileAttributesW.argtypes=[wintypes.LPCWSTR];kernel.GetFileAttributesW.restype=wintypes.DWORD
        kernel.SetFileAttributesW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD];kernel.SetFileAttributesW.restype=wintypes.BOOL
        attrs=kernel.GetFileAttributesW(str(source))|6
        assert kernel.SetFileAttributesW(str(source),attrs)
    before=tree(source)
    try:
        ipc('developer',request=dict(op='import_directory',root=str(source),target=str(target),username=credentials['user'],password='wrong-offline-password'))
    except RuntimeError:pass
    else:raise AssertionError('BAD_OFFLINE_PASSWORD_ACCEPTED')
    assert controller.root==original and before==tree(source) and not target.exists()
    sources=[source]
    if readonly is not None:
        sources.append(Path(readonly)/source.parent.name/source.name)
    for index, location in enumerate(sources):
        destination=target.with_name(target.name+str(index))
        result=ipc('developer',request=dict(op='import_directory',root=str(location),target=str(destination),username=credentials['user'],password=credentials['password']))
        assert result['ledger_id']==expected_ledger and result['daily']['hidden_dir']==''
        assert Path(result['source']['working_copy'])==destination
        ipc('bootstrap')
        orders=ipc('orders',q='',state='',offset=0,view='')
        assert orders['total']==1 and orders['orders'][0]['order_id']==expected_order
        assert before==tree(source)
        if attrs is not None:assert kernel.GetFileAttributesW(str(source))==attrs
        ipc('developer',request=dict(op='select',root=str(original),initialize=False,backup_dir=''))
        ipc('bootstrap')
