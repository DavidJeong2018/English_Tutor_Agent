"""Wires the selection watcher, translator, popup, tray icon and windows together."""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import win32api
import win32event
import winerror
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .config import SETTINGS_DIR, Settings
from .popup import TranslationPopup
from .selection import SelectionWatcher
from .translator import TranslationError, Translator, TutorResult
from .vocab import VocabEntry, VocabStore


def _asset(name: str) -> Path:
    """Finds a file in assets/, both when run from source and from the PyInstaller build."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / name


def make_icon() -> QIcon:
    ico = _asset("icon.ico")
    if ico.exists():
        return QIcon(str(ico))
    pix = QPixmap(64, 64)  # fallback if the assets folder is missing
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#2f5d9e"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    p.setPen(QColor("white"))
    p.setFont(QFont("Malgun Gothic", 26, QFont.Bold))
    p.drawText(pix.rect(), Qt.AlignCenter, "영")
    p.end()
    return QIcon(pix)


class _Job(QRunnable):
    def __init__(self, bridge: "Bridge", translator: Translator, request_id: int, text: str):
        super().__init__()
        self.bridge, self.translator, self.request_id, self.text = bridge, translator, request_id, text

    def run(self):
        try:
            result = self.translator.explain(self.text)
            self.bridge.result.emit(self.request_id, self.text, result)
        except TranslationError as e:
            self.bridge.error.emit(self.request_id, str(e))
        except Exception as e:  # never let a worker crash the app silently
            logging.getLogger(__name__).exception("translation failed")
            self.bridge.error.emit(self.request_id, f"오류: {e}")


class Bridge(QObject):
    """Carries events from background threads onto the Qt main thread."""
    selected = Signal(str)
    result = Signal(int, str, object)
    error = Signal(int, str)


class TutorApp:
    def __init__(self):
        self.qt = QApplication(sys.argv)
        self.qt.setQuitOnLastWindowClosed(False)
        self.qt.setFont(QFont("Malgun Gothic", 10))
        self.qt.setWindowIcon(make_icon())

        self.settings = Settings.load()
        self.store = VocabStore(self.settings.vocab_dir)
        self.translator = self._make_translator()
        self.pool = QThreadPool.globalInstance()
        self.request_id = 0

        self.bridge = Bridge()
        self.bridge.selected.connect(self.translate)
        self.bridge.result.connect(self._on_result)
        self.bridge.error.connect(self._on_error)

        self.popup = TranslationPopup(self.settings, on_save=self.save_entry, is_saved=self.store.contains)
        self.vocab_window = None

        self.watcher = SelectionWatcher(self.bridge.selected.emit, hotkey=self.settings.hotkey)
        self.watcher.auto_enabled = self.settings.auto_translate
        self._build_tray()

    def _make_translator(self) -> Translator:
        return Translator(self.settings.api_key, self.settings.model, self.settings.effort)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(make_icon())
        self.tray.setToolTip("English Tutor - 영어 문장을 선택하면 한국어로 번역합니다")
        menu = QMenu()
        self.auto_action = QAction("자동 번역 켜기", checkable=True, checked=self.settings.auto_translate)
        self.auto_action.toggled.connect(self._set_auto)
        menu.addAction(self.auto_action)
        menu.addAction("내 단어장", self.show_vocab)
        menu.addAction("설정", self.show_settings)
        menu.addSeparator()
        menu.addAction("종료", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.show_vocab() if reason == QSystemTrayIcon.DoubleClick else None)
        self._menu = menu  # keep a reference so it isn't garbage-collected

    # --- actions ---

    def translate(self, text: str) -> None:
        self.request_id += 1
        self.popup.show_loading(text)
        self.pool.start(_Job(self.bridge, self.translator, self.request_id, text))

    def _on_result(self, request_id: int, text: str, result: TutorResult) -> None:
        if request_id == self.request_id:  # ignore answers to older selections
            self.popup.show_result(text, result)

    def _on_error(self, request_id: int, message: str) -> None:
        if request_id == self.request_id:
            self.popup.show_error(message)

    def save_entry(self, entry: VocabEntry) -> bool:
        added = self.store.add(entry)
        if self.vocab_window and self.vocab_window.isVisible():
            self.vocab_window.refresh()
        return added

    def _set_auto(self, enabled: bool) -> None:
        self.watcher.auto_enabled = enabled
        self.settings.auto_translate = enabled
        self.settings.save()

    def show_vocab(self) -> None:
        from .windows import VocabWindow
        if self.vocab_window is None:
            self.vocab_window = VocabWindow(self.store)
        self.vocab_window.show()
        self.vocab_window.raise_()
        self.vocab_window.activateWindow()

    def show_settings(self) -> None:
        from .windows import SettingsDialog
        dialog = SettingsDialog(self.settings)
        if dialog.exec():
            self.settings = dialog.apply()
            self.translator = self._make_translator()
            self.auto_action.setChecked(self.settings.auto_translate)
            if str(self.store.folder) != self.settings.vocab_dir:
                self.store = VocabStore(self.settings.vocab_dir)
                self.popup._is_saved = self.store.contains
                if self.vocab_window:
                    self.vocab_window.store = self.store
                    self.vocab_window.refresh()

    def quit(self) -> None:
        self.watcher.stop()
        self.tray.hide()
        self.qt.quit()

    def run(self) -> int:
        self.watcher.start()
        self.tray.show()
        has_key = self.settings.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not has_key:
            QMessageBox.information(None, "English Tutor",
                                    "Anthropic API 키를 설정해 주세요.\n(트레이 아이콘 → 설정)")
            self.show_settings()
        self.tray.showMessage("English Tutor", "영어 문장을 드래그하면 한국어 번역이 표시됩니다.",
                              QSystemTrayIcon.Information, 3000)
        return self.qt.exec()


def _setup_logging() -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(SETTINGS_DIR / "tutor.log", maxBytes=500_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("english_tutor").setLevel(logging.DEBUG)


def main() -> None:
    _setup_logging()
    # Two running copies would both press Ctrl+C on every selection and fight over the clipboard.
    mutex = win32event.CreateMutex(None, False, "EnglishTutor.SingleInstance")
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        win32api.MessageBox(0, "English Tutor가 이미 실행 중입니다.\n작업 표시줄 오른쪽의 트레이 아이콘을 확인하세요.",
                            "English Tutor", 0x40)
        return
    logging.getLogger(__name__).info("English Tutor started")
    code = TutorApp().run()
    del mutex
    sys.exit(code)
