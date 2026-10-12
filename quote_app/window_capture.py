"""Capture an application window by HWND on Windows; never desktop coordinates."""
import os


def native_window_id(root):
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    get_ancestor = user32.GetAncestor
    get_ancestor.argtypes = [wintypes.HWND,wintypes.UINT]
    get_ancestor.restype = wintypes.HWND
    handle = get_ancestor(root.winfo_id(),2)
    if not handle:raise OSError('无法取得当前窗口句柄')
    return handle


def capture_window(root):
    from PIL import ImageGrab
    if os.name == 'nt':
        if root.state() == 'iconic':raise ValueError('请先还原窗口再保存窗口截图')
        try:image = ImageGrab.grab(window=native_window_id(root))
        except TypeError as exc:raise ValueError('窗口截图需要Pillow 11.2.1或以上版本') from exc
    else:
        # Existing headless adapter tests replace ImageGrab; no Linux product
        # claim. The actual Windows entry never uses Tk logical desktop bounds.
        x,y=root.winfo_rootx(),root.winfo_rooty()
        image=ImageGrab.grab(bbox=(x,y,x+root.winfo_width(),y+root.winfo_height()))
    if image.width <= 0 or image.height <= 0:
        image.close();raise ValueError('窗口截取为空，未保存')
    return image
