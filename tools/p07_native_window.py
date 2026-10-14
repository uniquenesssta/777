"""Close only the owned visible app window; measure exit independently of log EOF."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import time


class Windows:
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('ACTUAL_WINDOWS_REQUIRED')
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        signatures = {
            'EnumWindows': ([self.callback, wintypes.LPARAM], wintypes.BOOL),
            'GetWindowThreadProcessId': ([wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            'GetWindowTextW': ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            'GetClassNameW': ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            'IsWindowVisible': ([wintypes.HWND], wintypes.BOOL),
            'GetWindowRect': ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            'PostMessageW': ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.user, name)
            function.argtypes, function.restype = args, result

    def owned(self, pid):
        windows, errors = [], []

        def visit(hwnd, _):
            try:
                found = wintypes.DWORD()
                if not self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(found)):
                    return True  # Window may have disappeared during enumeration.
                if found.value != pid:
                    return True
                title, name, rect = ctypes.create_unicode_buffer(1024), ctypes.create_unicode_buffer(256), wintypes.RECT()
                self.user.GetWindowTextW(hwnd, title, len(title))
                if not self.user.GetClassNameW(hwnd, name, len(name)):
                    raise ctypes.WinError(ctypes.get_last_error())
                if not self.user.GetWindowRect(hwnd, ctypes.byref(rect)):
                    raise ctypes.WinError(ctypes.get_last_error())
                windows.append(dict(hwnd=int(hwnd), pid=found.value, title=title.value,
                                    class_name=name.value, visible=bool(self.user.IsWindowVisible(hwnd)),
                                    width=rect.right - rect.left, height=rect.bottom - rect.top))
                return True
            except Exception as error:
                errors.append(error)
                return False

        visitor = self.callback(visit)
        result = self.user.EnumWindows(visitor, 0)
        if errors:
            raise errors[0]
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        return windows

    def post_close(self, hwnd):
        if not self.user.PostMessageW(hwnd, 0x0010, 0, 0):
            raise ctypes.WinError(ctypes.get_last_error())


def main_window(windows, pid, title):
    candidates = [w for w in windows if w['pid'] == pid and w['title'] == title
                  and w['visible'] and w['width'] > 0 and w['height'] > 0
                  and w['class_name'] != 'Tao Thread Event Target']
    if len(candidates) != 1:
        raise RuntimeError(f'NATIVE_MAIN_WINDOW_NOT_UNIQUE: found {len(candidates)}')
    return candidates[0]


def close_window(process, title, diagnostic, *, windows=None, timeout=30):
    """One WM_CLOSE to the actual main HWND, then require a natural zero exit.

    No termination or retries here: forced cleanup must never turn into a pass.
    The caller redirects stdout/stderr to a file, so inherited WebView2 handles
    cannot make waiting for the desktop's exit depend on pipe EOF.
    """
    windows = windows if windows is not None else Windows()
    record = dict(status='checking', pid=process.pid, close_message_posted=False,
                  process_exit_observed=False, exit_code=process.poll(), forced_termination=False)
    start = time.monotonic()

    def save():
        Path(diagnostic).write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    try:
        record['windows_before'] = windows.owned(process.pid)
        if record['exit_code'] is not None:
            raise RuntimeError('NATIVE_PROCESS_EXITED_BEFORE_CLOSE')
        target = main_window(record['windows_before'], process.pid, title)
        record['target'] = target
        save()
        # Recheck ownership/title immediately before posting; do not target a reused HWND.
        current = main_window(windows.owned(process.pid), process.pid, title)
        if current['hwnd'] != target['hwnd']:
            raise RuntimeError('NATIVE_MAIN_WINDOW_CHANGED')
        windows.post_close(target['hwnd'])
        record['close_message_posted'] = True
        record['status'] = 'waiting_for_exit'
        save()
        try:
            record['exit_code'] = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            record['exit_code'] = process.poll()
            raise RuntimeError('NATIVE_MAIN_WINDOW_CLOSE_TIMEOUT') from error
        record['process_exit_observed'] = True
        if record['exit_code'] != 0:
            raise RuntimeError('NATIVE_PROCESS_EXIT_NONZERO')
        record['status'] = 'passed'
        return record
    except BaseException as error:
        record['status'] = 'interrupted' if isinstance(error, KeyboardInterrupt) else 'failed'
        record['failure'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        record['elapsed_seconds'] = round(time.monotonic() - start, 3)
        try:
            record['windows_after'] = windows.owned(process.pid)
        except Exception as error:
            record['enumeration_after_error'] = str(error)
        save()
