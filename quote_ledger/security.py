"""Protect only an explicitly new application-owned Windows backup directory."""
import os
import re
import subprocess
from .paths import LedgerError, local_path


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
    args=[os.path.join(system.value,'icacls.exe'),str(path),'/inheritance:r','/grant:r']
    args.extend('*'+value+':(OI)(CI)F' for value in sorted(allowed))
    subprocess.run(args,check=True,capture_output=True)
    # Read the real descriptor rather than parsing localized icacls text.
    advapi=ctypes.WinDLL('advapi32',use_last_error=True)
    get_security=advapi.GetNamedSecurityInfoW
    get_security.argtypes=[wintypes.LPWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)]
    get_security.restype=wintypes.DWORD
    convert=advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW
    convert.argtypes=[ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(wintypes.LPWSTR),ctypes.c_void_p];convert.restype=wintypes.BOOL
    free=kernel.LocalFree;free.argtypes=[ctypes.c_void_p];free.restype=ctypes.c_void_p
    descriptor=ctypes.c_void_p();sddl=wintypes.LPWSTR()
    try:
        error=get_security(str(path),1,4,None,None,None,None,ctypes.byref(descriptor))
        if error:raise ctypes.WinError(error)
        if not convert(descriptor,1,4,ctypes.byref(sddl),None):raise ctypes.WinError(ctypes.get_last_error())
        value=sddl.value
        # SID aliases for the only two built-in principals we grant.
        permitted=allowed|{'SY','BA'}
        entries=re.findall(r'\(([^()]+)\)',value)
        if not value.startswith('D:P') or len(entries)!=len(allowed):raise LedgerError('备份DACL保护/主体数量核验失败')
        for ace in entries:
            fields=ace.split(';')
            if len(fields)!=6 or fields[0]!='A' or fields[2]!='FA' or fields[5] not in permitted:
                raise LedgerError('备份DACL包含未授权主体或权限')
        attributes=get_attributes(str(path))
        if attributes==0xffffffff or attributes&6!=6:raise LedgerError('Hidden/System属性核验失败')
        return {'hidden':True,'system':True,'protected_dacl':True,'service_identity_sid':sid,'allowed_sids':sorted(allowed)}
    finally:
        if sddl:free(ctypes.cast(sddl,ctypes.c_void_p))
        if descriptor:free(descriptor)
