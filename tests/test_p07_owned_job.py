"""Windows cancellation owns grandchildren even when the package launcher exits first."""
import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from p07_owned_job import OwnedJob


@unittest.skipUnless(os.name == 'nt', 'actual Windows job required')
class OwnedJobTests(unittest.TestCase):
    def test_exited_parent_does_not_leave_owned_grandchild(self):
        owner = OwnedJob()
        code = "import subprocess,sys; sys.stdin.readline(); p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); print(p.pid,flush=True)"
        process = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        handle = None
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [w.DWORD,w.BOOL,w.DWORD]; kernel.OpenProcess.restype = w.HANDLE
        kernel.WaitForSingleObject.argtypes = [w.HANDLE,w.DWORD]; kernel.WaitForSingleObject.restype = w.DWORD
        kernel.CloseHandle.argtypes = [w.HANDLE]; kernel.CloseHandle.restype = w.BOOL
        try:
            owner.assign(process)
            process.stdin.write('start\n'); process.stdin.flush()
            pid = int(process.stdout.readline())
            handle = kernel.OpenProcess(0x100000, False, pid)
            self.assertTrue(handle)
            process.wait(timeout=10)
            self.assertEqual(kernel.WaitForSingleObject(handle,0),258)
            owner.close()
            self.assertEqual(kernel.WaitForSingleObject(handle,10000),0)
        finally:
            owner.close()
            if handle:kernel.CloseHandle(handle)
            process.communicate(timeout=10)


if __name__ == '__main__':unittest.main()
