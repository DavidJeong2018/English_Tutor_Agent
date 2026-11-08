"""Detects text the user copies or asks to translate in any Windows application.

Two triggers:
- The user highlights text and presses Ctrl+C. A global keyboard hook notices the
  key press, waits for the clipboard to change, and reads the copied text. The
  clipboard is left as the user copied it.
- The hotkey (Ctrl+Alt+T by default). We press Ctrl+C on the user's behalf, read
  the clipboard, then put the user's previous clipboard contents back.
"""
from __future__ import annotations

import ctypes
import logging
import os
import threading
import time
from typing import Callable, Optional, TypeVar

import pywintypes
import win32clipboard
import win32con
import win32gui
import win32process
from pynput import keyboard

log = logging.getLogger(__name__)
T = TypeVar("T")

# Windows whose Ctrl+C means "interrupt", not "copy".
CONSOLE_CLASSES = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "mintty", "PuTTY"}

CLIPBOARD_WAIT_S = 0.6
VK_C = 0x43
CTRL_KEYS = {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}


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


def _foreground_pid() -> int:
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return 0
    try:
        return win32process.GetWindowThreadProcessId(hwnd)[1]
    except Exception:
        return 0


def _foreground_is_safe() -> bool:
    """False for our own windows and terminals (where Ctrl+C kills programs)."""
    pid = _foreground_pid()
    if not pid or pid == os.getpid():
        return False
    return win32gui.GetClassName(win32gui.GetForegroundWindow()) not in CONSOLE_CLASSES


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
    """Calls `on_text(text)` from a background thread when the user copies English text."""

    def __init__(self, on_text: Callable[[str], None], hotkey: str = "<ctrl>+<alt>+t"):
        self._on_text = on_text
        self._hotkey = hotkey
        self.auto_enabled = True  # translate on Ctrl+C; the hotkey works either way
        self._ctrl_down = set()
        self._busy = threading.Lock()
        self._kb = keyboard.Controller()
        self._copy_listener: Optional[keyboard.Listener] = None
        self._hotkey_listener: Optional[keyboard.GlobalHotKeys] = None

    def start(self) -> None:
        self._copy_listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._copy_listener.start()
        self._hotkey_listener = keyboard.GlobalHotKeys({_vk_hotkey(self._hotkey): self._on_hotkey})
        self._hotkey_listener.start()

    def stop(self) -> None:
        for listener in (self._copy_listener, self._hotkey_listener):
            if listener:
                listener.stop()

    # --- event handlers (run on pynput threads; keep them fast) ---

    def _on_press(self, key, injected=False):
        if injected:  # our own Ctrl+C from the hotkey path
            return
        if key in CTRL_KEYS:
            self._ctrl_down.add(key)
            return
        if not self._ctrl_down or not self.auto_enabled or getattr(key, "vk", None) != VK_C:
            return
        # The hook runs before the app handles the key, so this is the pre-copy number.
        seq = _clipboard_seq()
        threading.Thread(target=self._run, args=(self._read_user_copy, seq), daemon=True).start()

    def _on_release(self, key, injected=False):
        if not injected:
            self._ctrl_down.discard(key)

    def _on_hotkey(self):
        # Wait for the user to let go of Ctrl+Alt+T so our Ctrl+C isn't mangled.
        threading.Thread(target=self._run, args=(self._copy_selection,), daemon=True).start()

    # --- capture ---

    def _run(self, capture: Callable, *args) -> None:
        if not self._busy.acquire(blocking=False):
            return  # a held-down Ctrl+C repeats; one capture is enough
        try:
            text = capture(*args)
            if text is not None:
                self._deliver(text)
        except Exception:
            log.exception("capturing the selection failed")
        finally:
            self._busy.release()

    @staticmethod
    def _wait_for_clipboard(seq: int) -> bool:
        deadline = time.monotonic() + CLIPBOARD_WAIT_S
        while _clipboard_seq() == seq and time.monotonic() < deadline:
            time.sleep(0.02)
        if _clipboard_seq() == seq:
            return False
        time.sleep(0.05)  # let the source app finish writing the clipboard
        return True

    def _read_user_copy(self, seq: int) -> Optional[str]:
        """The user pressed Ctrl+C themselves: read what they copied and leave it there."""
        if _foreground_pid() == os.getpid():
            return None  # copying from our own popup
        if not self._wait_for_clipboard(seq):
            log.debug("skipped: Ctrl+C didn't copy anything")
            return None
        return _read_clipboard_text()

    def _copy_selection(self) -> Optional[str]:
        """Hotkey: copy the selection for the user, then restore their clipboard."""
        time.sleep(0.3)
        if not _foreground_is_safe():
            log.debug("skipped: foreground window is a terminal or this app")
            return None
        previous = _read_clipboard_text()
        seq = _clipboard_seq()
        with self._kb.pressed(keyboard.Key.ctrl):
            self._kb.tap("c")
        if not self._wait_for_clipboard(seq):
            log.debug("skipped: nothing was copied (no text selected)")
            return None
        text = _read_clipboard_text()
        _write_clipboard_text(previous)
        return text

    def _deliver(self, text: str) -> None:
        text = " ".join(text.split())  # PDFs break lines mid-sentence
        if not text or len(text) > 3000 or not looks_like_english(text):
            log.debug("skipped: copied text is empty, too long or not English (%d chars)", len(text))
            return
        log.info("captured %d chars", len(text))
        self._on_text(text)
