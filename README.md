# English Tutor Agent (영어 도우미)

A Windows desktop app for Korean speakers reading English. Highlight English text in any
app — a PDF reader, a browser, Word — and a popup shows:

- **번역**: a natural Korean translation of the selection
- **표현 설명**: idioms, phrasal verbs and expressions in the text, explained in Korean with an example
- **단어**: harder words with their Korean meaning in context, each with a **저장** (save) button

Saved words go to your own vocabulary list, stored on your computer.

## Setup

Requires Windows and Python 3.9 or newer.

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

Or double-click `run.bat`, which does the same and runs the app without a console window.

The app uses the Claude API, so you need an Anthropic API key from
https://console.anthropic.com. Either set the `ANTHROPIC_API_KEY` environment variable or
paste the key in **Settings (설정)** the first time the app starts.

## How to use

The app runs in the system tray (the blue **영** icon).

| Action | Result |
| --- | --- |
| Drag to highlight English text, or double-click a word | Popup with the translation appears next to the cursor |
| `Ctrl+Alt+T` | Translates the current selection (works even when auto-translate is off) |
| **저장** in the popup | Saves the word to your vocabulary list |
| 📌 in the popup | Keeps the popup where you dragged it |
| `Esc` or ✕ | Closes the popup |
| Tray icon → **내 단어장** (or double-click the icon) | Opens your vocabulary list: search, delete, open folder |
| Tray icon → **자동 번역 켜기** | Turns automatic translation on selection on or off |

## Where things are stored

| File | Location |
| --- | --- |
| Vocabulary | `Documents\EnglishTutor\vocabulary.json` and `vocabulary.csv` (opens in Excel); the folder can be changed in Settings |
| Settings | `%APPDATA%\EnglishTutor\settings.json` |

## How it works

- `english_tutor/selection.py` watches the mouse globally. When a drag-select or double-click
  ends, it presses `Ctrl+C`, reads the copied text, then puts your previous clipboard text back.
  It skips terminal windows, where `Ctrl+C` would stop a running program.
- `english_tutor/translator.py` sends the text to Claude (`claude-opus-5-5` at low effort by
  default) and gets back structured JSON: translation, phrases, vocabulary. Results are cached
  so selecting the same sentence twice doesn't call the API again.
- `english_tutor/popup.py`, `windows.py` and `app.py` are the PySide6 UI and tray icon.
- `english_tutor/vocab.py` stores saved words as JSON and CSV.

## Notes

- Some apps don't support copying (protected PDFs, images of text). Nothing will appear for those.
- If you copy an image and then highlight text, only text is put back on the clipboard.
- Model and effort level can be changed in Settings. Lower-cost models such as
  `claude-haiku-5-5` respond faster and cost less per translation.
