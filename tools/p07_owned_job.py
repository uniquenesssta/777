"""Windows job for a build process waiting on its private start pipe.

https://learn.microsoft.com/windows/win32/procthread/job-objects
Closing the only job handle terminates all descendants, even after Node exits.
"""
import ctypes
from ctypes import wintypes as w
import os


class BasicLimits(ctypes.Structure):
    _fields_ = [('ProcessTime', ctypes.c_int64), ('JobTime', ctypes.c_int64),
                ('LimitFlags', w.DWORD), ('MinimumWorkingSet', ctypes.c_size_t),
                ('MaximumWorkingSet', ctypes.c_size_t), ('ActiveProcessLimit', w.DWORD),
                ('Affinity', ctypes.c_size_t), ('PriorityClass', w.DWORD), ('SchedulingClass', w.DWORD)]


class Counters(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ['ReadOps','WriteOps','OtherOps','ReadBytes','WriteBytes','OtherBytes']]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [('Basic', BasicLimits), ('Io', Counters), ('ProcessMemory', ctypes.c_size_t),
                ('JobMemory', ctypes.c_size_t), ('PeakProcess', ctypes.c_size_t), ('PeakJob', ctypes.c_size_t)]


class OwnedJob:
    def __init__(self):
        if os.name != 'nt':raise RuntimeError('ACTUAL_WINDOWS_REQUIRED')
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        for name, args, result in [
            ('CreateJobObjectW', [ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
            ('SetInformationJobObject', [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
            ('AssignProcessToJobObject', [w.HANDLE, w.HANDLE], w.BOOL),
            ('CloseHandle', [w.HANDLE], w.BOOL),
        ]:
            call = getattr(self.kernel, name); call.argtypes = args; call.restype = result
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits(); limits.Basic.LimitFlags = 0x2000
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error()); self.close(); raise error

    def assign(self, process):
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            if not self.kernel.CloseHandle(self.handle):raise ctypes.WinError(ctypes.get_last_error())
            self.handle = None
