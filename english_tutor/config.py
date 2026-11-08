"""User settings, stored as JSON in %APPDATA%\\EnglishTutor\\settings.json."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "EnglishTutor"
SETTINGS_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
SETTINGS_FILE = SETTINGS_DIR / "settings.json"
DEFAULT_VOCAB_DIR = Path.home() / "Documents" / APP_NAME


@dataclass
class Settings:
    api_key: str = ""  # empty -> use the ANTHROPIC_API_KEY environment variable
    model: str = "claude-opus-5-5"
    effort: str = "low"  # low keeps the popup fast; raise for harder texts
    auto_translate: bool = True
    hotkey: str = "<ctrl>+<alt>+t"
    vocab_dir: str = field(default_factory=lambda: str(DEFAULT_VOCAB_DIR))
    font_size: int = 12  # popup text size in points
    popup_width: int = 480
    popup_height: int = 0  # 0 -> fit the content; set once the user resizes the popup

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self) -> None:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
