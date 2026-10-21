"""
Open-window helpers: list windows, find one by name, capture ONE window (even behind others), focus it.

Why this exists: the built-in screen_process grabs monitor 1, so it only ever sees what is on top of that
screen. Here a window is found by its title or program name and captured on its own:

  1. PrintWindow(PW_RENDERFULLCONTENT) asks Windows to paint that window into a bitmap, so a window that
     is covered by other windows still comes out whole. Some GPU / protected windows return black.
  2. Fallback: if the picture is blank, the window is restored and brought to the front, and its rectangle is
     grabbed from the screen. The caller is told, because that visibly changes the desktop.

Windows only (ctypes, no extra packages). On other systems list_windows() is empty and capture_window()
grabs the primary screen, which the caller reports.
The leading underscore keeps the plugin loader from treating this file as a plugin.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass

IS_WIN = sys.platform == "win32"


@dataclass
class Win:
    hwnd: int
    title: str
    exe: str
    pid: int
    rect: tuple[int, int, int, int]
    minimized: bool
    foreground: bool = False


_ALIASES = {
    "vs code": ["code"], "vscode": ["code"], "visual studio code": ["code"], "code editor": ["code"],
    "google chrome": ["chrome"], "edge": ["msedge"], "microsoft edge": ["msedge"], "firefox": ["firefox"],
    "whats app": ["whatsapp"], "whatsapp web": ["whatsapp"], "file explorer": ["explorer"], "explorer": ["explorer"],
    "files": ["explorer"], "word": ["winword"], "ms word": ["winword"], "powerpoint": ["powerpnt"],
    "excel": ["excel"], "teams": ["ms-teams", "teams"], "terminal": ["windowsterminal", "cmd", "powershell"],
    "command prompt": ["cmd"], "cmd": ["cmd"], "task manager": ["taskmgr"], "calculator": ["calculatorapp", "calc"],
    "obs": ["obs64", "obs"], "obs studio": ["obs64"], "pycharm": ["pycharm64"], "android studio": ["studio64"],
    "paint": ["mspaint"], "media player": ["vlc", "wmplayer", "video"],
}


def rank(query: str, wins: list[Win]) -> list[Win]:
    """Best match first. Matches a window title or program name."""
    q0 = (query or "").strip().lower()
    if not q0:
        return []
    qs = [q0] + _ALIASES.get(q0, [])
    scored = []
    for w in wins:
        t, e = w.title.lower(), w.exe.lower().removesuffix(".exe")
        best = None
        for q in qs:
            if t == q or e == q: s = 0
            elif t.startswith(q) or e.startswith(q): s = 1
            elif q in t or q in e: s = 2
            elif all(tok in f"{t} {e}" for tok in q.split()): s = 3
            else: continue
            best = s if best is None else min(best, s)
        if best is not None:
            scored.append((best, 0 if w.foreground else 1,
                           -(w.rect[2]-w.rect[0])*(w.rect[3]-w.rect[1]), w))
    scored.sort(key=lambda x: x[:3])
    return [x[3] for x in scored]


def is_blank(img) -> bool:
    """True for an all-black / single-colour capture (PrintWindow failed)."""
    try:
        lo, hi = img.convert("L").resize((48, 48)).getextrema()
        return (hi - lo) < 6
    except Exception:
        return True


if IS_WIN:
    import ctypes
    from ctypes import wintypes
    _u = ctypes.windll.user32
    _g = ctypes.windll.gdi32
    try: _dwm = ctypes.windll.dwmapi
    except Exception: _dwm = None
    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _u.IsWindowVisible.argtypes = [wintypes.HWND]
    _u.IsIconic.argtypes = [wintypes.HWND]
    _u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _u.GetWindowDC.argtypes = [wintypes.HWND]; _u.GetWindowDC.restype = wintypes.HDC
    _u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _u.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    _u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]; _u.GetWindowLongW.restype = wintypes.LONG
    _u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]; _u.GetWindow.restype = wintypes.HWND
    _u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _u.SetForegroundWindow.argtypes = [wintypes.HWND]
    _u.GetForegroundWindow.argtypes = []; _u.GetForegroundWindow.restype = wintypes.HWND
    _u.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    _g.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    _g.CreateCompatibleDC.argtypes = [wintypes.HDC]; _g.CreateCompatibleDC.restype = wintypes.HDC
    _g.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    _g.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    _g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]; _g.SelectObject.restype = wintypes.HGDIOBJ
    _g.DeleteObject.argtypes = [wintypes.HGDIOBJ]; _g.DeleteDC.argtypes = [wintypes.HDC]

    class _BMIH(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    def _title(hwnd):
        n = _u.GetWindowTextLengthW(hwnd)
        if n <= 0: return ""
        buf = ctypes.create_unicode_buffer(n + 1); _u.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def _cloaked(hwnd):
        if _dwm is None: return False
        v = wintypes.DWORD(0)
        try: _dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(v), ctypes.sizeof(v))
        except Exception: return False
        return bool(v.value)

    def _frame_rect(hwnd):
        r = wintypes.RECT()
        if _dwm is not None:
            try:
                if _dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) == 0:
                    return r.left, r.top, r.right, r.bottom
            except Exception: pass
        _u.GetWindowRect(hwnd, ctypes.byref(r))
        return r.left, r.top, r.right, r.bottom

    def _exe_of(pid):
        try:
            import psutil
            return psutil.Process(pid).name()
        except Exception: return ""

    def list_windows() -> list[Win]:
        found = []
        fg = _u.GetForegroundWindow()
        @_WNDENUMPROC
        def cb(hwnd, _lp):
            try:
                if not _u.IsWindowVisible(hwnd) and not _u.IsIconic(hwnd): return True
                title = _title(hwnd)
                if not title or _cloaked(hwnd): return True
                if _u.GetWindowLongW(hwnd, -20) & 0x80 and not _u.GetWindow(hwnd, 4): return True
                pid = wintypes.DWORD(0); _u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                found.append(Win(int(hwnd), title, _exe_of(pid.value), pid.value, _frame_rect(hwnd),
                                 bool(_u.IsIconic(hwnd)), hwnd == fg))
            except Exception: pass
            return True
        _u.EnumWindows(cb, 0)
        return [w for w in found if w.title != "Program Manager"]

    def focus_window(win: Win):
        if _u.IsIconic(win.hwnd): _u.ShowWindow(win.hwnd, 9)
        _u.keybd_event(0x12, 0, 0, 0); _u.keybd_event(0x12, 0, 2, 0)
        _u.SetForegroundWindow(win.hwnd); time.sleep(0.35)

    def _printwindow(win: Win):
        from PIL import Image
        l, t, r, b = win.rect
        full = wintypes.RECT(); _u.GetWindowRect(win.hwnd, ctypes.byref(full))
        w, h = full.right-full.left, full.bottom-full.top
        if w <= 0 or h <= 0 or w > 16000 or h > 16000: return None
        hdc_win = _u.GetWindowDC(win.hwnd); hdc = _g.CreateCompatibleDC(hdc_win)
        bmp = _g.CreateCompatibleBitmap(hdc_win, w, h); old = _g.SelectObject(hdc, bmp)
        try:
            if not _u.PrintWindow(win.hwnd, hdc, 2): return None
            bmi = _BMIH(ctypes.sizeof(_BMIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
            buf = ctypes.create_string_buffer(w*h*4)
            if not _g.GetDIBits(hdc, bmp, 0, h, buf, ctypes.byref(bmi), 0): return None
            img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
            dx, dy = max(0, l-full.left), max(0, t-full.top)
            return img.crop((dx, dy, min(w, dx+r-l), min(h, dy+b-t))).copy()
        finally:
            _g.SelectObject(hdc, old); _g.DeleteObject(bmp); _g.DeleteDC(hdc); _u.ReleaseDC(win.hwnd, hdc_win)
else:
    def list_windows() -> list[Win]: return []
    def focus_window(win: Win): return None
    def _printwindow(win: Win): return None


def _grab_rect(rect):
    import mss
    from PIL import Image
    l, t, r, b = rect
    with mss.mss() as sct:
        shot = sct.grab({"left": l, "top": t, "width": max(1,r-l), "height": max(1,b-t)})
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def capture_window(win: Win, allow_foreground: bool = True):
    """Returns (PIL image, method): printwindow, foreground or screen."""
    if IS_WIN:
        try:
            img = _printwindow(win)
            if img is not None and not win.minimized and not is_blank(img): return img, "printwindow"
        except Exception: pass
        if not allow_foreground:
            raise RuntimeError("That window can't be captured while hidden or minimised.")
        focus_window(win); img = _grab_rect(_frame_rect(win.hwnd))
        if is_blank(img): raise RuntimeError("That window comes out blank (it may be protected content).")
        return img, "foreground"
    import mss
    from PIL import Image
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[1])
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX"), "screen"


def monitor_count() -> int:
    import mss
    with mss.mss() as sct: return max(1, len(sct.monitors)-1)


def capture_screen(monitor="all"):
    """Capture all monitors side-by-side or one numbered display."""
    import mss
    from PIL import Image
    with mss.mss() as sct:
        mons = sct.monitors; want = 0
        s = str(monitor or "all").strip().lower()
        if s.isdigit() and int(s) > 0:
            want = int(s)
            if want >= len(mons):
                raise RuntimeError(f"I only see {len(mons)-1} screens.")
        elif len(mons) == 2: want = 1
        shot = sct.grab(mons[want])
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    if want == 0: what = f"all {len(mons)-1} screens side by side"
    elif len(mons) == 2: what = "the screen"
    else: what = f"screen {want}"
    return img, what
