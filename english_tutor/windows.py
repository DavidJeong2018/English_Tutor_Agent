"""Vocabulary list window and settings dialog."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .config import Settings
from .vocab import VocabStore

COLUMNS = [("word", "단어 / 표현"), ("part_of_speech", "품사"), ("meaning_ko", "뜻"),
           ("explanation_ko", "설명"), ("example_en", "예문"), ("source", "원문"), ("added_at", "저장일")]


class VocabWindow(QWidget):
    def __init__(self, store: VocabStore):
        super().__init__()
        self.store = store
        self.setWindowTitle("내 단어장 - English Tutor")
        self.resize(1150, 550)

        top = QHBoxLayout()
        self.search = QLineEdit(placeholderText="검색 (단어, 표현 또는 뜻)")
        self.search.textChanged.connect(self.refresh)
        top.addWidget(self.search, 1)
        delete_btn = QPushButton("선택 삭제")
        delete_btn.clicked.connect(self._delete_selected)
        folder_btn = QPushButton("폴더 열기")
        folder_btn.clicked.connect(self._open_folder)
        top.addWidget(delete_btn)
        top.addWidget(folder_btn)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([title for _, title in COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        for i, width in enumerate([140, 60, 150, 220, 200, 200]):
            self.table.setColumnWidth(i, width)
        header.setStretchLastSection(True)

        self.count_label = QLabel()
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table)
        layout.addWidget(self.count_label)

    def refresh(self) -> None:
        query = self.search.text().strip().lower()
        rows = [e for e in reversed(self.store.entries)
                if not query or query in e.word.lower() or query in e.meaning_ko.lower()]
        self.table.setRowCount(len(rows))
        for r, entry in enumerate(rows):
            for c, (key, _) in enumerate(COLUMNS):
                item = QTableWidgetItem(getattr(entry, key))
                item.setToolTip(getattr(entry, key))
                self.table.setItem(r, c, item)
        self.table.resizeRowsToContents()
        self.count_label.setText(f"총 {len(self.store.entries)}개 · {self.store.json_path}")

    def showEvent(self, e):
        self.refresh()
        super().showEvent(e)

    def _delete_selected(self) -> None:
        words = {self.table.item(i.row(), 0).text() for i in self.table.selectionModel().selectedRows()}
        if not words:
            return
        if QMessageBox.question(self, "삭제", f"{len(words)}개 단어를 삭제할까요?") != QMessageBox.Yes:
            return
        for w in words:
            self.store.remove(w)
        self.refresh()

    def _open_folder(self) -> None:
        self.store.folder.mkdir(parents=True, exist_ok=True)
        os.startfile(self.store.folder)


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정 - English Tutor")
        self.setMinimumWidth(480)
        self.settings = settings

        self.api_key = QLineEdit(settings.api_key, echoMode=QLineEdit.Password,
                                 placeholderText="비워두면 ANTHROPIC_API_KEY 환경변수를 사용")
        self.model = QComboBox(editable=True)
        self.model.addItems(["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"])
        self.model.setCurrentText(settings.model)
        self.effort = QComboBox()
        self.effort.addItems(["low", "medium", "high"])
        self.effort.setCurrentText(settings.effort)
        self.auto = QCheckBox("텍스트를 선택하고 Ctrl+C를 누르면 번역", checked=settings.auto_translate)
        self.vocab_dir = QLineEdit(settings.vocab_dir)
        browse = QPushButton("찾아보기…")
        browse.clicked.connect(self._browse)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.vocab_dir, 1)
        dir_row.addWidget(browse)

        form = QFormLayout()
        form.addRow("Anthropic API 키", self.api_key)
        form.addRow("모델", self.model)
        form.addRow("추론 수준 (effort)", self.effort)
        form.addRow("", self.auto)
        form.addRow("단어장 폴더", dir_row)
        hint = QLabel(f"단축키 {settings.hotkey.replace('<', '').replace('>', '').upper()}: 선택한 텍스트 번역")
        hint.setStyleSheet("color: #6b7280;")
        form.addRow("", hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons, alignment=Qt.AlignRight)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "단어장 폴더 선택", self.vocab_dir.text())
        if folder:
            self.vocab_dir.setText(folder)

    def apply(self) -> Settings:
        s = self.settings
        s.api_key = self.api_key.text().strip()
        s.model = self.model.currentText().strip()
        s.effort = self.effort.currentText()
        s.auto_translate = self.auto.isChecked()
        s.vocab_dir = self.vocab_dir.text().strip() or s.vocab_dir
        s.save()
        return s
