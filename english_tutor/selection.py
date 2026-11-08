"""Detects text the user highlights in any Windows application.

Strategy: a global mouse hook watches for a drag-select or double-click.
When one ends, we press Ctrl+C on the user's behalf, read the clipboard,
and then put the user's previous clipboard contents back.
"""
from __future__ import annotations

import ctypes
import logging
import math
import os
import threading
import time
from typing import Callable, Optional, TypeVar

import pywintypes
import win32clipboard
import win32con
import win32gui
import win32process
from pynput import keyboard, mouse

log = logging.getLogger(__name__)
T = TypeVar("T")

# Windows whose Ctrl+C means "interrupt", not "copy".
CONSOLE_CLASSES = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "mintty", "PuTTY"}

DRAG_MIN_PX = 8
DOUBLE_CLICK_S = 0.45
COPY_SETTLE_S = 0.15
CLIPBOARD_WAIT_S = 0.6


def _with_clipboard(action: Callable[[], T], attempts: int = 10) -> Optional[T]:
    """Runs `action` with the clipboard open, retrying while another program holds it.

    Other programs (PDF readers especially) open the clipboard at the same moment
    we do, which makes OpenClipboard or GetClipboardData fail; that is not fatal.
    """
    for _ in range(attempts):
        try:
            win32clipboard.OpenClipboard()
        except pywintypes.error:
            time.sleep(0.03)
            continue
        try:
            return action()
        except pywintypes.error as e:
            log.debug("clipboard busy, retrying: %s", e)
        finally:
            try:
                win32clipboard.CloseClipboard()
            except pywintypes.error:
                pass
        time.sleep(0.03)
    log.warning("gave up on the clipboard after %d attempts", attempts)
    return None


def _read_clipboard_text() -> Optional[str]:
    def read():
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        return None
    return _with_clipboard(read)


def _write_clipboard_text(text: Optional[str]) -> None:
    def write():
        win32clipboard.EmptyClipboard()
        if text is not None:
            win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
        return True
    _with_clipboard(write)


def _clipboard_seq() -> int:
    return ctypes.windll.user32.GetClipboardSequenceNumber()


def _foreground_is_safe() -> bool:
    """False for our own windows and terminals (where Ctrl+C kills programs)."""
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return False
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
    except Exception:
        return False
    if pid == os.getpid():
        return False
    return win32gui.GetClassName(hwnd) not in CONSOLE_CLASSES


def _point_is_ours(x: int, y: int) -> bool:
    """True when the click landed on one of this app's windows (e.g. the popup)."""
    try:
        hwnd = win32gui.WindowFromPoint((int(x), int(y)))
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
    except Exception:
        return False
    return pid == os.getpid()


def _vk_hotkey(hotkey: str) -> str:
    """Rewrites '<ctrl>+<alt>+t' as '<ctrl>+<alt>+<84>'.

    With Ctrl+Alt held, Windows reports letter keys by virtual-key code only, so a
    hotkey written with the letter itself never matches a real key press.
    """
    parts = []
    for part in hotkey.split("+"):
        if len(part) == 1 and part.isascii() and part.isalnum():
            part = f"<{ord(part.upper())}>"  # A-Z and 0-9 virtual-key codes are their ASCII codes
        parts.append(part)
    return "+".join(parts)


def looks_like_english(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 2:
        return False
    latin = sum(1 for c in letters if c.isascii())
    return latin / len(letters) > 0.7


class SelectionWatcher:
    """Calls `on_text(text)` from a background thread whenever English text is highlighted."""

    def __init__(self, on_text: Callable[[str], None], hotkey: str = "<ctrl>+<alt>+t"):
        self._on_text = on_text
        self._hotkey = hotkey
        self.auto_enabled = True
        self._press_pos = None
        self._last_click_t = 0.0
        self._busy = threading.Lock()
        self._kb = keyboard.Controller()
        self._mouse_listener: Optional[mouse.Listener] = None
        self._hotkey_listener: Optional[keyboard.GlobalHotKeys] = None

    def start(self) -> None:
        self._mouse_listener = mouse.Listener(on_click=self._on_click)
        self._mouse_listener.start()
        self._hotkey_listener = keyboard.GlobalHotKeys({_vk_hotkey(self._hotkey): self._on_hotkey})
        self._hotkey_listener.start()

    def stop(self) -> None:
        for listener in (self._mouse_listener, self._hotkey_listener):
            if listener:
                listener.stop()

    # --- event handlers (run on pynput threads; keep them fast) ---

    def _on_click(self, x, y, button, pressed):
        if button != mouse.Button.left:
            return
        if pressed:
            self._press_pos = (x, y)
            return
        if not self.auto_enabled or self._press_pos is None or _point_is_ours(x, y):
            return
        now = time.monotonic()
        dragged = math.dist(self._press_pos, (x, y)) >= DRAG_MIN_PX
        double = now - self._last_click_t < DOUBLE_CLICK_S
        self._last_click_t = now
        if dragged or double:
            threading.Thread(target=self._capture, daemon=True).start()

    def _on_hotkey(self):
        # Wait for the user to let go of Ctrl+Alt+T so our Ctrl+C isn't mangled.
        threading.Thread(target=self._capture, kwargs={"delay": 0.3}, daemon=True).start()

    # --- capture ---

    def _capture(self, delay: float = COPY_SETTLE_S) -> None:
        if not self._busy.acquire(blocking=False):
            return
        try:
            self._capture_once(delay)
        except Exception:
            log.exception("capturing the selection failed")
        finally:
            self._busy.release()

    def _capture_once(self, delay: float) -> None:
        time.sleep(delay)
        if not _foreground_is_safe():
            log.debug("skipped: foreground window is a terminal or this app")
            return
        previous = _read_clipboard_text()
        seq = _clipboard_seq()
        with self._kb.pressed(keyboard.Key.ctrl):
            self._kb.tap("c")
        deadline = time.monotonic() + CLIPBOARD_WAIT_S
        while _clipboard_seq() == seq and time.monotonic() < deadline:
            time.sleep(0.02)
        if _clipboard_seq() == seq:
            log.debug("skipped: nothing was copied (no text selected)")
            return
        time.sleep(0.05)  # let the source app finish writing the clipboard
        text = (_read_clipboard_text() or "").strip()
        _write_clipboard_text(previous)
        text = " ".join(text.split())  # PDFs break lines mid-sentence
        if not text or len(text) > 3000 or not looks_like_english(text):
            log.debug("skipped: copied text is empty, too long or not English (%d chars)", len(text))
            return
        log.info("captured %d chars", len(text))
        self._on_text(text)
