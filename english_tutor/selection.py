"""Detects text the user highlights in any Windows application.

Strategy: a global mouse hook watches for a drag-select or double-click.
When one ends, we press Ctrl+C on the user's behalf, read the clipboard,
and then put the user's previous clipboard contents back.
"""
from __future__ import annotations

import ctypes
import math
import os
import threading
import time
from typing import Callable, Optional

import win32clipboard
import win32con
import win32gui
import win32process
from pynput import keyboard, mouse

# Windows whose Ctrl+C means "interrupt", not "copy".
CONSOLE_CLASSES = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "mintty", "PuTTY"}

DRAG_MIN_PX = 8
DOUBLE_CLICK_S = 0.45
COPY_SETTLE_S = 0.15
CLIPBOARD_WAIT_S = 0.6


def _read_clipboard_text() -> Optional[str]:
    for _ in range(5):
        try:
            win32clipboard.OpenClipboard()
        except Exception:
            time.sleep(0.03)
            continue
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            return None
        finally:
            win32clipboard.CloseClipboard()
    return None


def _write_clipboard_text(text: Optional[str]) -> None:
    for _ in range(5):
        try:
            win32clipboard.OpenClipboard()
        except Exception:
            time.sleep(0.03)
            continue
        try:
            win32clipboard.EmptyClipboard()
            if text is not None:
                win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
            return
        finally:
            win32clipboard.CloseClipboard()


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
        self._last_text = ""
        self._busy = threading.Lock()
        self._kb = keyboard.Controller()
        self._mouse_listener: Optional[mouse.Listener] = None
        self._hotkey_listener: Optional[keyboard.GlobalHotKeys] = None

    def start(self) -> None:
        self._mouse_listener = mouse.Listener(on_click=self._on_click)
        self._mouse_listener.start()
        self._hotkey_listener = keyboard.GlobalHotKeys({self._hotkey: self._on_hotkey})
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
            threading.Thread(target=self._capture, args=(False,), daemon=True).start()

    def _on_hotkey(self):
        # Wait for the user to let go of Ctrl+Alt+T so our Ctrl+C isn't mangled.
        threading.Thread(target=self._capture, args=(True,), kwargs={"delay": 0.3}, daemon=True).start()

    # --- capture ---

    def _capture(self, forced: bool, delay: float = COPY_SETTLE_S) -> None:
        if not self._busy.acquire(blocking=False):
            return
        try:
            time.sleep(delay)
            if not _foreground_is_safe():
                return
            previous = _read_clipboard_text()
            seq = _clipboard_seq()
            with self._kb.pressed(keyboard.Key.ctrl):
                self._kb.tap("c")
            deadline = time.monotonic() + CLIPBOARD_WAIT_S
            while _clipboard_seq() == seq and time.monotonic() < deadline:
                time.sleep(0.02)
            if _clipboard_seq() == seq:
                return  # nothing was selected, so nothing was copied
            text = (_read_clipboard_text() or "").strip()
            _write_clipboard_text(previous)
            text = " ".join(text.split())  # PDFs break lines mid-sentence
            if not text or len(text) > 3000 or not looks_like_english(text):
                return
            if text == self._last_text and not forced:
                return
            self._last_text = text
            self._on_text(text)
        finally:
            self._busy.release()
