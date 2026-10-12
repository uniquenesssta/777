"""Per-Windows-user encrypted pending requests; passwords/tokens are never saved."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import uuid

from .protocol import APIError,decode


def dpapi(raw, *, decrypt=False):
    if os.name!='nt':raise APIError(400,'WINDOWS_DPAPI_REQUIRED')
    class Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buffer=ctypes.create_string_buffer(raw);source=Blob(len(raw),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)))
    entropy_buffer=ctypes.create_string_buffer(b'777-pending-v1')
    entropy=Blob(14,ctypes.cast(entropy_buffer,ctypes.POINTER(ctypes.c_ubyte)))
    crypt=ctypes.WinDLL('crypt32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    free=kernel.LocalFree;free.argtypes=[ctypes.c_void_p];free.restype=ctypes.c_void_p
    output=Blob()
    if decrypt:
        operation=crypt.CryptUnprotectData
        operation.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
        arguments=[ctypes.byref(source),None,ctypes.byref(entropy),None,None,1,ctypes.byref(output)]
    else:
        operation=crypt.CryptProtectData
        operation.argtypes=[ctypes.POINTER(Blob),wintypes.LPCWSTR,ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
        arguments=[ctypes.byref(source),'777 pending request',ctypes.byref(entropy),None,None,1,ctypes.byref(output)]
    operation.restype=wintypes.BOOL
    try:
        if not operation(*arguments):raise APIError(503,'PENDING_DPAPI_FAILED')
        return ctypes.string_at(output.data,output.size)
    finally:
        if output.data:free(ctypes.cast(output.data,ctypes.c_void_p))


class Journal:
    def __init__(self,path):
        if os.name!='nt':raise APIError(400,'WINDOWS_DPAPI_REQUIRED')
        self.path=Path(path).absolute()

    def read(self):
        if not self.path.exists():return None
        raw=self.path.read_bytes()
        if len(raw)>2*1024*1024:raise APIError(422,'PENDING_TOO_LARGE')
        return decode(dpapi(raw,decrypt=True))

    def write(self,value):
        if self.read() is not None:raise APIError(409,'PENDING_REQUEST_REQUIRES_QUERY')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_name('.'+self.path.name+'.'+str(uuid.uuid4())+'.tmp')
        try:
            fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'wb') as stream:
                stream.write(dpapi(json.dumps(value,ensure_ascii=False).encode('utf-8')));stream.flush();os.fsync(stream.fileno())
            # One owner per client profile is enforced by the launcher lock.
            os.replace(temp,self.path)
        finally:
            try:temp.unlink()
            except FileNotFoundError:pass

    def clear(self):
        try:self.path.unlink()
        except FileNotFoundError:pass


class MemoryJournal:
    """Explicit transient fixture adapter; never a production disk fallback."""
    def __init__(self):self.value=None
    def read(self):return json.loads(json.dumps(self.value)) if self.value is not None else None
    def write(self,value):
        if self.value is not None:raise APIError(409,'PENDING_REQUEST_REQUIRES_QUERY')
        self.value=json.loads(json.dumps(value))
    def clear(self):self.value=None
