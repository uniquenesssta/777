"""Windows-only owned process: visible app plus Tao-shaped event helper."""
import ctypes
from ctypes import wintypes as w
import json
from pathlib import Path
import sys

user, kernel = ctypes.WinDLL('user32', use_last_error=True), ctypes.WinDLL('kernel32', use_last_error=True)
callback = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)


class WindowClass(ctypes.Structure):
    _fields_ = [('style', w.UINT), ('lpfnWndProc', callback), ('cbClsExtra', ctypes.c_int),
                ('cbWndExtra', ctypes.c_int), ('hInstance', w.HINSTANCE), ('hIcon', w.HICON),
                ('hCursor', w.HANDLE), ('hbrBackground', w.HBRUSH), ('lpszMenuName', w.LPCWSTR),
                ('lpszClassName', w.LPCWSTR)]


user.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user.DefWindowProcW.restype = ctypes.c_ssize_t
user.RegisterClassW.argtypes, user.RegisterClassW.restype = [ctypes.POINTER(WindowClass)], w.WORD
user.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]
user.CreateWindowExW.restype = w.HWND
user.IsWindow.argtypes, user.IsWindow.restype = [w.HWND], w.BOOL
user.DestroyWindow.argtypes, user.DestroyWindow.restype = [w.HWND], w.BOOL
user.PostQuitMessage.argtypes, user.PostQuitMessage.restype = [ctypes.c_int], None
user.GetMessageW.argtypes, user.GetMessageW.restype = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT], w.BOOL
user.TranslateMessage.argtypes, user.TranslateMessage.restype = [ctypes.POINTER(w.MSG)], w.BOOL
user.DispatchMessageW.argtypes, user.DispatchMessageW.restype = [ctypes.POINTER(w.MSG)], ctypes.c_ssize_t
kernel.GetModuleHandleW.argtypes, kernel.GetModuleHandleW.restype = [w.LPCWSTR], w.HMODULE
helper = None


@callback
def window_proc(hwnd, message, wp, lp):
    if message == 0x0010 and hwnd != helper:
        # Closing the helper first is the old broad EnumWindows bug.
        intact = bool(user.IsWindow(helper))
        user.DestroyWindow(hwnd)
        user.PostQuitMessage(0 if intact else 7)
        return 0
    return user.DefWindowProcW(hwnd, message, wp, lp)


instance = kernel.GetModuleHandleW(None)
for name in ['Tao Thread Event Target', '777 lifecycle fixture']:
    definition = WindowClass(lpfnWndProc=window_proc, hInstance=instance, lpszClassName=name)
    if not user.RegisterClassW(ctypes.byref(definition)):
        raise ctypes.WinError(ctypes.get_last_error())
# The real Tao helper also carries WS_VISIBLE despite having no UI/area.
helper = user.CreateWindowExW(0x080000A0, 'Tao Thread Event Target', '', 0x90000000,
                             0, 0, 0, 0, None, None, instance, None)
main = user.CreateWindowExW(0, '777 lifecycle fixture', '记账器', 0x10CF0000,
                           0, 0, 320, 180, None, None, instance, None)
if not helper or not main:
    raise ctypes.WinError(ctypes.get_last_error())
ready = Path(sys.argv[1])
pending = ready.with_suffix('.tmp')
pending.write_text(json.dumps({'helper': int(helper), 'main': int(main)}), encoding='utf-8')
pending.replace(ready)
message = w.MSG()
while True:
    result = user.GetMessageW(ctypes.byref(message), None, 0, 0)
    if result == -1:
        raise ctypes.WinError(ctypes.get_last_error())
    if result == 0:
        break
    user.TranslateMessage(ctypes.byref(message))
    user.DispatchMessageW(ctypes.byref(message))
raise SystemExit(message.wParam)
