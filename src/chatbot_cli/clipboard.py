import ctypes
import time
from ctypes import wintypes

from prompt_toolkit.clipboard import Clipboard, ClipboardData


class WindowsClipboard(Clipboard):
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002

    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32

        self.user32.OpenClipboard.argtypes = [wintypes.HWND]
        self.user32.OpenClipboard.restype = wintypes.BOOL
        self.user32.CloseClipboard.argtypes = []
        self.user32.CloseClipboard.restype = wintypes.BOOL
        self.user32.EmptyClipboard.argtypes = []
        self.user32.EmptyClipboard.restype = wintypes.BOOL
        self.user32.GetClipboardData.argtypes = [wintypes.UINT]
        self.user32.GetClipboardData.restype = wintypes.HANDLE
        self.user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        self.user32.SetClipboardData.restype = wintypes.HANDLE

        self.kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        self.kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        self.kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        self.kernel32.GlobalLock.restype = wintypes.LPVOID
        self.kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        self.kernel32.GlobalUnlock.restype = wintypes.BOOL
        self.kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        self.kernel32.GlobalFree.restype = wintypes.HGLOBAL

    def _open(self) -> bool:
        for _ in range(5):
            if self.user32.OpenClipboard(None):
                return True
            time.sleep(0.02)
        return False

    def get_data(self) -> ClipboardData:
        if not self._open():
            return ClipboardData("")
        try:
            handle = self.user32.GetClipboardData(self.CF_UNICODETEXT)
            if not handle:
                return ClipboardData("")
            locked = self.kernel32.GlobalLock(handle)
            if not locked:
                return ClipboardData("")
            try:
                return ClipboardData(ctypes.wstring_at(locked).rstrip("\r\n"))
            finally:
                self.kernel32.GlobalUnlock(handle)
        except Exception:
            return ClipboardData("")
        finally:
            self.user32.CloseClipboard()

    def set_data(self, data: ClipboardData) -> None:
        if not self._open():
            return
        handle = None
        clipboard_owns_handle = False
        try:
            text = data.text or ""
            buffer = ctypes.create_unicode_buffer(text)
            size = ctypes.sizeof(buffer)
            handle = self.kernel32.GlobalAlloc(self.GMEM_MOVEABLE, size)
            if not handle:
                return
            locked = self.kernel32.GlobalLock(handle)
            if not locked:
                return
            try:
                ctypes.memmove(locked, buffer, size)
            finally:
                self.kernel32.GlobalUnlock(handle)

            self.user32.EmptyClipboard()
            if self.user32.SetClipboardData(self.CF_UNICODETEXT, handle):
                clipboard_owns_handle = True
        except Exception:
            pass
        finally:
            self.user32.CloseClipboard()
            if handle and not clipboard_owns_handle:
                self.kernel32.GlobalFree(handle)
