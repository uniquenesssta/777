"""Protect only an explicitly new application-owned Windows backup directory."""
import os
import re
import subprocess
from .paths import LedgerError, local_path


def _verify_dacl_sddl(value, allowed):
    """Require an exact protected allow-list, including child inheritance."""
    match = re.fullmatch(r'D:((?:P|AR|AI)*)(\([^()]*\)(?:\([^()]*\))*)', value or '')
    if not match or 'P' not in match[1]:
        raise LedgerError('备份DACL未受保护或描述符格式不支持')
    entries = re.findall(r'\(([^()]*)\)', match[2])
    if len(entries) != len(allowed):
        raise LedgerError(f'备份DACL主体数量核验失败：expected={len(allowed)}, actual={len(entries)}')
    aliases = {'SY': 'S-1-5-18', 'BA': 'S-1-5-32-544'}
    seen = set()
    for entry in entries:
        fields = entry.split(';')
        if (len(fields) != 6 or fields[0] != 'A' or fields[1] not in {'OICI', 'CIOI'}
                or fields[2].lower() not in {'fa', '0x1f01ff', '0x001f01ff'}
                or fields[3] or fields[4]):
            raise LedgerError('备份DACL包含未授权权限、ACE类型或继承标志')
        principal = aliases.get(fields[5], fields[5])
        if principal not in allowed or principal in seen:
            raise LedgerError('备份DACL包含未授权或重复主体')
        seen.add(principal)
    if seen != allowed:
        raise LedgerError('备份DACL缺少必要主体')


def _replace_dacl(path, allowed, advapi, free):
    """Replace the new owned directory's entire DACL, rather than merge grants."""
    import ctypes
    from ctypes import wintypes
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    convert.restype = wintypes.BOOL
    get_dacl = advapi.GetSecurityDescriptorDacl
    get_dacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    get_dacl.restype = wintypes.BOOL
    set_security = advapi.SetNamedSecurityInfoW
    set_security.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    set_security.restype = wintypes.DWORD
    value = 'D:P' + ''.join(f'(A;OICI;FA;;;{sid})' for sid in sorted(allowed))
    descriptor = ctypes.c_void_p()
    try:
        if not convert(value, 1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        if not get_dacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not present.value or not dacl or defaulted.value:
            raise LedgerError('备份DACL必须为显式非空权限列表')
        # DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION.
        error = set_security(str(path), 1, 0x80000004, None, None, dacl, None)
        if error:
            raise ctypes.WinError(error)
    finally:
        if descriptor:
            free(descriptor)


def protect_directory(path):
    path=local_path(path,directory=True)
    if os.name!='nt':raise LedgerError('Hidden/System与ACL仅在Windows实施')
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    get_attributes=kernel.GetFileAttributesW;get_attributes.argtypes=[wintypes.LPCWSTR];get_attributes.restype=wintypes.DWORD
    set_attributes=kernel.SetFileAttributesW;set_attributes.argtypes=[wintypes.LPCWSTR,wintypes.DWORD];set_attributes.restype=wintypes.BOOL
    get_system=kernel.GetSystemDirectoryW;get_system.argtypes=[wintypes.LPWSTR,wintypes.UINT];get_system.restype=wintypes.UINT
    system=ctypes.create_unicode_buffer(32768)
    size=get_system(system,len(system))
    if not size or size>=len(system):raise LedgerError('Windows系统工具目录不可确认')
    before=get_attributes(str(path))
    if before==0xffffffff:raise ctypes.WinError(ctypes.get_last_error())
    if not set_attributes(str(path),before|0x2|0x4):raise ctypes.WinError(ctypes.get_last_error())
    sid_output=subprocess.run([os.path.join(system.value,'whoami.exe'),'/user','/fo','csv','/nh'],check=True,capture_output=True).stdout
    matches=re.findall(rb'S-1-5-[0-9-]+',sid_output)
    if len(matches)!=1:raise LedgerError('当前服务身份SID不可确认')
    sid=matches[0].decode('ascii');allowed={sid,'S-1-5-18','S-1-5-32-544'}
    # Write an exact DACL and independently read the resulting descriptor.
    advapi=ctypes.WinDLL('advapi32',use_last_error=True)
    get_security=advapi.GetNamedSecurityInfoW
    get_security.argtypes=[wintypes.LPWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)]
    get_security.restype=wintypes.DWORD
    convert=advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW
    convert.argtypes=[ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(wintypes.LPWSTR),ctypes.c_void_p];convert.restype=wintypes.BOOL
    free=kernel.LocalFree;free.argtypes=[ctypes.c_void_p];free.restype=ctypes.c_void_p
    _replace_dacl(path,allowed,advapi,free)
    descriptor=ctypes.c_void_p();sddl=wintypes.LPWSTR()
    try:
        error=get_security(str(path),1,4,None,None,None,None,ctypes.byref(descriptor))
        if error:raise ctypes.WinError(error)
        if not convert(descriptor,1,4,ctypes.byref(sddl),None):raise ctypes.WinError(ctypes.get_last_error())
        value=sddl.value
        _verify_dacl_sddl(value,allowed)
        attributes=get_attributes(str(path))
        if attributes==0xffffffff or attributes&6!=6:raise LedgerError('Hidden/System属性核验失败')
        return {'hidden':True,'system':True,'protected_dacl':True,'service_identity_sid':sid,'allowed_sids':sorted(allowed)}
    finally:
        if sddl:free(ctypes.cast(sddl,ctypes.c_void_p))
        if descriptor:free(descriptor)
