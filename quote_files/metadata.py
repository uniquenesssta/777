"""Read-only file version probes. No data reads, retained handles or writes."""
from dataclasses import dataclass
from functools import cache
import os
import stat


@dataclass(frozen=True)
class FileVersion:
    size: int
    mtime_ns: int
    token: tuple
    strong: bool
    backend: str


def canonical(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


@cache
def windows_api():
    import ctypes as c
    from ctypes import wintypes as w
    class Basic(c.Structure):
        _fields_ = [(name, c.c_longlong) for name in ("creation", "access", "write", "change")] + [("attributes", w.DWORD)]
    class Standard(c.Structure):
        _fields_ = [("allocation", c.c_longlong), ("size", c.c_longlong), ("links", w.DWORD),
                    ("deleted", c.c_ubyte), ("directory", c.c_ubyte)]
    class Identity(c.Structure):
        _fields_ = [("volume", c.c_ulonglong), ("identifier", c.c_ubyte * 16)]
    api = c.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    api.CreateFileW.restype = w.HANDLE
    api.GetFileInformationByHandleEx.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
    api.GetFileInformationByHandleEx.restype = w.BOOL
    api.CloseHandle.argtypes = [w.HANDLE];api.CloseHandle.restype = w.BOOL
    return api, Basic, Standard, Identity


def windows_version(path):
    import ctypes as c
    api, Basic, Standard, Identity = windows_api()
    # FILE_READ_ATTRIBUTES, all sharing including rename/delete, OPEN_EXISTING.
    handle = api.CreateFileW(os.fspath(path), 0x80, 7, None, 3, 0x80, None)
    if handle == c.c_void_p(-1).value:
        return None
    try:
        basic, standard, identity = Basic(), Standard(), Identity()
        for kind, value in ((0, basic), (1, standard), (0x12, identity)):
            if not api.GetFileInformationByHandleEx(handle, kind, c.byref(value), c.sizeof(value)):
                return None
        identifier = bytes(identity.identifier)
        token = (identity.volume, identifier, basic.creation, basic.write, basic.change,
                 basic.attributes, standard.size)
        strong = bool(any(identifier) and basic.change and basic.write % 10000000)
        return FileVersion(standard.size, (basic.write - 116444736000000000) * 100,
                           token, strong, "windows-file-basic-id" if strong else "windows-weak-time")
    finally:
        api.CloseHandle(handle)


def file_version(path):
    info = os.stat(path)
    if not stat.S_ISREG(info.st_mode):
        raise OSError("不是可读取的普通文件")
    if os.name == "nt":
        version = windows_version(path)
        if version is not None:
            return version
        return FileVersion(info.st_size, info.st_mtime_ns,
            (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns), False,
            "windows-provider-unverified")
    # This branch is auxiliary-container evidence, not another product target.
    strong = bool(info.st_ino and info.st_mtime_ns % 1000000000 and info.st_ctime_ns % 1000000000)
    return FileVersion(info.st_size, info.st_mtime_ns,
        (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns), strong,
        "auxiliary-stat" if strong else "auxiliary-weak-time")
