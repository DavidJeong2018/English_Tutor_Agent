"""Floating popup that shows the Korean translation next to the mouse cursor."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizeGrip, QVBoxLayout, QWidget,
)

from .config import Settings
from .translator import TutorResult, Word

MIN_FONT, MAX_FONT = 9, 24
MIN_WIDTH, MIN_HEIGHT = 320, 140


def _style(pt: int) -> str:
    return f"""
#card {{ background: #ffffff; border: 1px solid #c9ced6; border-radius: 10px; }}
#header {{ background: #2f5d9e; border-top-left-radius: 10px; border-top-right-radius: 10px; }}
#title {{ color: white; font-weight: 600; font-size: 10pt; }}
#headerBtn {{ color: white; background: transparent; border: none; font-size: 10pt; padding: 2px 6px; }}
#headerBtn:hover {{ background: rgba(255,255,255,0.2); border-radius: 4px; }}
#headerBtn:checked {{ background: rgba(255,255,255,0.35); border-radius: 4px; }}
#body {{ background: white; }}
#body QLabel {{ font-size: {pt}pt; color: #111827; }}
#body QLabel#source {{ color: #6b7280; font-size: {pt - 1}pt; }}
#body QLabel#section {{ color: #2f5d9e; font-weight: 700; font-size: {pt - 1}pt; margin-top: 6px; }}
#body QLabel#translation {{ font-size: {pt + 2}pt; }}
#body QLabel#status {{ color: #6b7280; }}
#body QLabel#error {{ color: #b42318; }}
#phrase {{ background: #f3f6fb; border-radius: 6px; }}
QPushButton#save {{ border: 1px solid #2f5d9e; color: #2f5d9e; background: white; border-radius: 4px;
                   padding: 2px 8px; font-size: {pt - 1}pt; }}
QPushButton#save:hover {{ background: #e8eef8; }}
QPushButton#save:disabled {{ border-color: #9ca3af; color: #9ca3af; }}
"""


def _label(text: str, name: str = "") -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(True)
    lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lbl


class TranslationPopup(QWidget):
    def __init__(self, settings: Settings, on_save_word: Callable[[Word, str], bool],
                 is_saved: Callable[[str], bool]):
        # WA_ShowWithoutActivating keeps keyboard focus in the user's PDF reader.
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)
        self.settings = settings
        self._on_save_word = on_save_word
        self._is_saved = is_saved
        self._drag_offset: Optional[QPoint] = None
        self._source_text = ""
        self._render_last: Callable[[], None] = lambda: None
        self._sizing = False  # True while we resize the popup ourselves
        self._save_timer = QTimer(self, singleShot=True, interval=600, timeout=self.settings.save)

        card = QFrame(objectName="card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        header = QFrame(objectName="header")
        h = QHBoxLayout(header)
        h.setContentsMargins(10, 4, 4, 4)
        h.setSpacing(2)
        h.addWidget(QLabel("English Tutor · 영어 도우미", objectName="title"))
        h.addStretch()
        smaller = QPushButton("가-", objectName="headerBtn", toolTip="글자 작게 (Ctrl+휠)")
        bigger = QPushButton("가+", objectName="headerBtn", toolTip="글자 크게 (Ctrl+휠)")
        smaller.clicked.connect(lambda: self.change_font(-1))
        bigger.clicked.connect(lambda: self.change_font(+1))
        self.pin_btn = QPushButton("📌", objectName="headerBtn", checkable=True, toolTip="고정 (다음 선택 때 위치 유지)")
        close_btn = QPushButton("✕", objectName="headerBtn", toolTip="닫기 (Esc)")
        close_btn.clicked.connect(self.hide)
        for b in (smaller, bigger, self.pin_btn, close_btn):
            h.addWidget(b)
        card_layout.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.viewport().installEventFilter(self)
        self.body = QWidget(objectName="body")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(12, 8, 12, 4)
        self.body_layout.setSpacing(4)
        self.scroll.setWidget(self.body)
        card_layout.addWidget(self.scroll, 1)

        # Bottom-right handle for resizing; the frameless window has no borders to drag.
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 2, 2)
        footer.addStretch()
        grip = QSizeGrip(self)
        grip.setToolTip("드래그하여 크기 조절")
        footer.addWidget(grip, 0, Qt.AlignBottom | Qt.AlignRight)
        card_layout.addLayout(footer)

        self.setStyleSheet(_style(self.settings.font_size))
        self.resize(self.settings.popup_width, self.settings.popup_height or 200)

    # --- content ---

    def _clear(self) -> None:
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            if item.widget():
                item.widget().hide()  # deleteLater() only removes it on the next event-loop pass
                item.widget().deleteLater()

    def _preview(self, text: str) -> QLabel:
        return _label(text if len(text) < 300 else text[:300] + "…", "source")

    def _finish(self) -> None:
        self.body_layout.addStretch()
        # Widgets added while the popup is already visible stay hidden (and are left
        # out of the height calculation) until shown explicitly.
        for i in range(self.body_layout.count()):
            widget = self.body_layout.itemAt(i).widget()
            if widget:
                widget.show()
        self.body_layout.invalidate()
        width = max(MIN_WIDTH, self.settings.popup_width)
        if self.settings.popup_height:
            height = self.settings.popup_height
        else:
            inner_w = width - 2 - self.scroll.verticalScrollBar().sizeHint().width()
            content_h = self.body_layout.heightForWidth(inner_w) + 56
            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            height = min(int(screen.availableGeometry().height() * 0.6), max(MIN_HEIGHT, content_h))
        self._sizing = True
        self.resize(width, height)
        self._sizing = False
        self._place()
        self.show()
        self.raise_()

    def show_loading(self, text: str) -> None:
        self._source_text = text
        self._render_last = lambda: self.show_loading(text)
        self._clear()
        self.body_layout.addWidget(self._preview(text))
        self.body_layout.addWidget(_label("번역 중…", "status"))
        self._finish()

    def show_error(self, message: str) -> None:
        self._render_last = lambda: self.show_error(message)
        self._clear()
        self.body_layout.addWidget(self._preview(self._source_text))
        self.body_layout.addWidget(_label(message, "error"))
        self._finish()

    def show_result(self, text: str, result: TutorResult) -> None:
        self._source_text = text
        self._render_last = lambda: self.show_result(text, result)
        self._clear()
        add = self.body_layout.addWidget
        add(self._preview(text))

        add(_label("번역", "section"))
        add(_label(result.translation, "translation"))

        if result.phrases:
            add(_label("표현 설명", "section"))
            for p in result.phrases:
                box = QFrame(objectName="phrase")
                v = QVBoxLayout(box)
                v.setContentsMargins(8, 6, 8, 6)
                v.setSpacing(2)
                v.addWidget(_label(f"<b>{p.phrase}</b> — {p.meaning_ko}"))
                v.addWidget(_label(p.explanation_ko))
                v.addWidget(_label(f"<i>예) {p.example_en}</i>"))
                add(box)

        if result.vocabulary:
            add(_label("단어", "section"))
            for w in result.vocabulary:
                add(self._word_row(w))
        self._finish()

    def _word_row(self, w: Word) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 2, 0, 2)
        info = _label(f"<b>{w.word}</b> <span style='color:#6b7280'>({w.part_of_speech})</span> {w.meaning_ko}"
                      f"<br><span style='color:#6b7280'><i>{w.example_en}</i></span>")
        h.addWidget(info, 1)
        btn = QPushButton("저장", objectName="save")
        if self._is_saved(w.word):
            btn.setText("저장됨")
            btn.setEnabled(False)

        def save():
            self._on_save_word(w, self._source_text)
            btn.setText("저장됨")
            btn.setEnabled(False)

        btn.clicked.connect(save)
        h.addWidget(btn, 0, Qt.AlignTop)
        return row

    # --- text size ---

    def change_font(self, step: int) -> None:
        size = min(MAX_FONT, max(MIN_FONT, self.settings.font_size + step))
        if size == self.settings.font_size:
            return
        self.settings.font_size = size
        self.setStyleSheet(_style(size))
        self._save_timer.start()
        pinned = self.pin_btn.isChecked()
        self.pin_btn.setChecked(True)  # re-render in place instead of jumping to the cursor
        self._render_last()
        self.pin_btn.setChecked(pinned)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and event.modifiers() & Qt.ControlModifier:
            self.change_font(1 if event.angleDelta().y() > 0 else -1)
            return True
        return super().eventFilter(obj, event)

    # --- size, position and dragging ---

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self._sizing and self.isVisible():  # the user dragged the size grip
            self.settings.popup_width = self.width()
            self.settings.popup_height = self.height()
            self._save_timer.start()

    def _place(self) -> None:
        if self.pin_btn.isChecked() and self.isVisible():
            return
        pos = QCursor.pos() + QPoint(16, 20)
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(pos.x(), area.right() - self.width())
        y = pos.y()
        if y + self.height() > area.bottom():
            y = QCursor.pos().y() - self.height() - 12
        self.move(max(area.left(), x), max(area.top(), y))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None:
            self.move(e.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, e):
        self._drag_offset = None

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide()
