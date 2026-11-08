"""Saved vocabulary, kept in <vocab_dir>/vocabulary.json (plus a CSV copy for Excel)."""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List

FIELDS = ["word", "part_of_speech", "meaning_ko", "example_en", "source", "added_at"]


@dataclass
class VocabEntry:
    word: str
    meaning_ko: str
    part_of_speech: str = ""
    example_en: str = ""
    source: str = ""  # the sentence the word was highlighted in
    added_at: str = ""


class VocabStore:
    def __init__(self, folder: str):
        self.folder = Path(folder)
        self.json_path = self.folder / "vocabulary.json"
        self.csv_path = self.folder / "vocabulary.csv"
        self.entries: List[VocabEntry] = self._load()

    def _load(self) -> List[VocabEntry]:
        try:
            raw = json.loads(self.json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [VocabEntry(**{k: item.get(k, "") for k in FIELDS}) for item in raw]

    def _save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        data = [asdict(e) for e in self.entries]
        tmp = self.json_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.json_path)
        # utf-8-sig so Excel shows Korean correctly
        with open(self.csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(data)

    def contains(self, word: str) -> bool:
        key = word.strip().lower()
        return any(e.word.lower() == key for e in self.entries)

    def add(self, entry: VocabEntry) -> bool:
        """Returns False if the word is already saved."""
        if self.contains(entry.word):
            return False
        entry.added_at = entry.added_at or datetime.now().strftime("%Y-%m-%d %H:%M")
        self.entries.append(entry)
        self._save()
        return True

    def remove(self, word: str) -> None:
        key = word.lower()
        self.entries = [e for e in self.entries if e.word.lower() != key]
        self._save()
