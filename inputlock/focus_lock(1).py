"""
Focus Lock — a self-control utility for Windows.

What it does:
  - Blocks keyboard input and mouse clicks system-wide (mouse can still MOVE,
    so you can see the cursor; clicks just don't register on anything).
  - The desktop, taskbar, and all your apps keep running normally underneath —
    nothing is frozen and nothing is covered by an overlay.
  - The one thing that still works is clicking on the taskbar / system tray,
    so you can reach this app's tray icon.
  - Clicking the tray icon opens a small "type to unlock" box. Type the
    correct phrase and everything goes back to normal.

This is a personal-discipline / focus tool, not a security product:
  - Ctrl+Alt+Del still works (Windows reserves that combo — it can't be
    intercepted by any app), so you always have an escape hatch via Task
    Manager if something goes wrong.
  - Anyone with access to Task Manager can end the python.exe process and
    bypass the lock instantly. That's intentional — this is meant to be a
    deliberate speed-bump you impose on yourself, not a way to lock a device
    against someone else's will.

Setup:
    pip install pystray pillow

Run:
    python focus_lock.py

Customize the unlock phrase below before running.
"""

import ctypes
from ctypes import wintypes
import threading
import time
import tkinter as tk

from PIL import Image, ImageDraw
import pystray

# ----------------------------------------------------------------------------
# CONFIG — change this before you run it
# ----------------------------------------------------------------------------
LOCK_PHRASE = "i am back"          # what you have to type to unlock
STARTUP_DELAY_SECONDS = 3          # grace period before the lock engages

# ----------------------------------------------------------------------------
# Win32 plumbing
# ----------------------------------------------------------------------------
user32 = ctypes.windll.user32

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_RBUTTONDBLCLK = 0x0206
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MBUTTONDBLCLK = 0x0209
WM_MOUSEWHEEL = 0x020A  # not blocked — scrolling isn't a click

CLICK_MESSAGES = {
    WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK,
    WM_RBUTTONDOWN, WM_RBUTTONUP, WM_RBUTTONDBLCLK,
    WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MBUTTONDBLCLK,
}


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_int, wintypes.WPARAM, ctypes.POINTER(KBDLLHOOKSTRUCT)
)
LowLevelMouseProc = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_int, wintypes.WPARAM, ctypes.POINTER(MSLLHOOKSTRUCT)
)

user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD
]
user32.CallNextHookEx.restype = ctypes.c_long
user32.CallNextHookEx.argtypes = [
    ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, ctypes.c_void_p
]
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint
]
user32.FindWindowW.restype = ctypes.c_void_p
user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.WindowFromPoint.restype = ctypes.c_void_p
user32.WindowFromPoint.argtypes = [POINT]
user32.GetAncestor.restype = ctypes.c_void_p
user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int

GA_ROOT = 2

# Window classes used (across Win10/11) for the taskbar, the system tray,
# and the "hidden icons" overflow flyout. Matched as substrings so we don't
# need to chase the exact class name on every Windows version.
TRAY_CLASS_KEYWORDS = ("tray", "notifyicon", "overflow")

# Virtual-key codes that stay usable even while locked: arrow keys + F1-F24.
ALLOWED_VK_CODES = {0x25, 0x26, 0x27, 0x28} | set(range(0x70, 0x88))

# ----------------------------------------------------------------------------
# Shared state between the hook thread, the tray thread, and the UI thread
# ----------------------------------------------------------------------------
state = {
    "locked": False,        # becomes True after the startup delay
    "popup_open": False,
    "popup_hwnd": None,
}
state_lock = threading.Lock()


def point_in_rect(x, y, rect):
    return rect.left <= x <= rect.right and rect.top <= y <= rect.bottom


def is_tray_related_window(hwnd):
    """True if hwnd belongs to the taskbar, the notification area, or the
    'hidden icons' overflow flyout — wherever Windows happens to draw it."""
    if not hwnd:
        return False
    root_hwnd = user32.GetAncestor(hwnd, GA_ROOT) or hwnd
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(root_hwnd, buf, 256)
    cls = buf.value.lower()
    return any(k in cls for k in TRAY_CLASS_KEYWORDS)


def low_level_keyboard_handler(nCode, wParam, lParam):
    if nCode == 0 and state["locked"]:
        allow = False
        if state["popup_open"] and state["popup_hwnd"]:
            if user32.GetForegroundWindow() == state["popup_hwnd"]:
                allow = True
        if not allow and lParam.contents.vkCode in ALLOWED_VK_CODES:
            allow = True
        if not allow:
            return 1
    return user32.CallNextHookEx(None, nCode, wParam, lParam)


def low_level_mouse_handler(nCode, wParam, lParam):
    if nCode == 0 and state["locked"]:
        msg = wParam
        if msg in CLICK_MESSAGES:
            pt = lParam.contents.pt
            allowed = False

            hwnd_at_point = user32.WindowFromPoint(pt)
            if is_tray_related_window(hwnd_at_point):
                allowed = True

            if state["popup_open"] and state["popup_hwnd"]:
                prect = wintypes.RECT()
                user32.GetWindowRect(state["popup_hwnd"], ctypes.byref(prect))
                if point_in_rect(pt.x, pt.y, prect):
                    allowed = True

            if not allowed:
                return 1
    return user32.CallNextHookEx(None, nCode, wParam, lParam)


def hook_thread_func():
    kb_proc = LowLevelKeyboardProc(low_level_keyboard_handler)
    ms_proc = LowLevelMouseProc(low_level_mouse_handler)

    kb_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, kb_proc, None, 0)
    ms_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, ms_proc, None, 0)

    if not kb_hook or not ms_hook:
        print("Failed to install input hooks. Try running from a normal "
              "(non-restricted) console.")
        return

    msg = wintypes.MSG()
    while True:
        ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if ret == 0:
            break

    user32.UnhookWindowsHookEx(kb_hook)
    user32.UnhookWindowsHookEx(ms_hook)


# ----------------------------------------------------------------------------
# Tkinter UI (hidden root + unlock popup)
# ----------------------------------------------------------------------------
root = tk.Tk()
root.withdraw()


def open_popup():
    if state["popup_open"]:
        return

    popup = tk.Toplevel(root)
    popup.title("Locked")
    popup.resizable(False, False)
    popup.attributes("-topmost", True)

    w, h = 340, 150
    sw, sh = popup.winfo_screenwidth(), popup.winfo_screenheight()
    popup.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    # Disable the window-close [X] while locked, so closing the box can't
    # be used to bypass typing the phrase.
    popup.protocol("WM_DELETE_WINDOW", lambda: None)

    tk.Label(popup, text="Type the phrase to unlock:",
             font=("Segoe UI", 11)).pack(pady=(18, 6))

    entry = tk.Entry(popup, font=("Segoe UI", 12), width=30, justify="center")
    entry.pack(pady=4)

    status = tk.Label(popup, text="", fg="#b00020", font=("Segoe UI", 9))
    status.pack(pady=(2, 0))

    def try_unlock(event=None):
        if entry.get().strip().lower() == LOCK_PHRASE.lower():
            state["locked"] = False
            state["popup_open"] = False
            state["popup_hwnd"] = None
            popup.destroy()
        else:
            status.config(text="Incorrect phrase — try again.")
            entry.delete(0, tk.END)

    entry.bind("<Return>", try_unlock)
    tk.Button(popup, text="Unlock", width=12, command=try_unlock).pack(pady=10)

    popup.update_idletasks()
    state["popup_hwnd"] = popup.winfo_id()
    state["popup_open"] = True

    popup.deiconify()
    popup.lift()
    popup.focus_force()
    entry.focus_set()


# ----------------------------------------------------------------------------
# Tray icon
# ----------------------------------------------------------------------------
def make_icon_image(locked: bool):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = (200, 60, 60, 255) if locked else (60, 160, 90, 255)
    d.rounded_rectangle((14, 28, 50, 54), radius=4, outline=color, width=4)
    d.arc((20, 10, 44, 38), start=180, end=360, fill=color, width=4)
    return img


def on_unlock_clicked(icon, item=None):
    root.after(0, open_popup)


def on_exit(icon, item=None):
    icon.stop()
    root.after(0, root.destroy)


def run_tray():
    menu = pystray.Menu(
        pystray.MenuItem("Unlock", on_unlock_clicked, default=True),
        pystray.MenuItem("Exit", on_exit),
    )
    icon = pystray.Icon("focus_lock", make_icon_image(True),
                         "Focus Lock — click to unlock", menu)
    icon.run()


# ----------------------------------------------------------------------------
# Startup
# ----------------------------------------------------------------------------
def engage_lock_after_delay():
    print(f"Focus Lock starting — input will lock in {STARTUP_DELAY_SECONDS}s.")
    print("(Ctrl+Alt+Del always still works as an emergency way out.)")
    time.sleep(STARTUP_DELAY_SECONDS)
    state["locked"] = True
    print(f'Locked. Click the tray icon and type "{LOCK_PHRASE}" to unlock.')


def main():
    threading.Thread(target=hook_thread_func, daemon=True).start()
    threading.Thread(target=run_tray, daemon=True).start()
    threading.Thread(target=engage_lock_after_delay, daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    main()
