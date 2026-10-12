"""Explicit host-local paths; no SMB/mapped drive or link traversal."""
import os
from pathlib import Path
import stat


class LedgerError(Exception):pass
class Conflict(LedgerError):pass
class Forbidden(LedgerError):pass
class InvalidDatabase(LedgerError):pass
class UnknownCommit(LedgerError):
    def __init__(self, request_id):
        self.request_id = request_id
        super().__init__('提交结果待查询：' + request_id)


def local_path(value, *, directory=False, exists=True):
    text = os.fspath(value)
    if not text or text.startswith(('\\\\','//')) or text in {':memory:'} or text.startswith('file:'):
        raise LedgerError('账本/备份仅允许显式主机本地路径')
    path = Path(text)
    if not path.is_absolute():raise LedgerError('需要绝对路径')
    if os.name == 'nt':
        import ctypes
        get_drive = ctypes.WinDLL('kernel32', use_last_error=True).GetDriveTypeW
        get_drive.argtypes = [ctypes.c_wchar_p];get_drive.restype = ctypes.c_uint
        if get_drive(path.anchor) != 3:raise LedgerError('账本/备份需要本机固定磁盘')
    for part in (path, *path.parents):
        try:info = part.lstat()
        except FileNotFoundError:
            if part != path or exists:raise LedgerError('目录或文件不存在')
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0) & 0x400:
            raise LedgerError('拒绝链接/重解析路径')
        if part != path or directory:
            if not stat.S_ISDIR(info.st_mode):raise LedgerError('需要普通目录')
        elif not stat.S_ISREG(info.st_mode):raise LedgerError('需要普通文件')
    return path
