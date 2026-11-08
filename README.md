# English Tutor Agent (영어 도우미)

A Windows desktop app for Korean speakers reading English. Highlight English text in any
app — a PDF reader, a browser, Word — then press and release `Ctrl+Alt`. A popup shows:

- **번역**: a natural Korean translation of the selection
- **표현 설명**: idioms, phrasal verbs and expressions in the text, explained in Korean with an example, each with a **저장** (save) button
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

## Sharing with someone who doesn't have Python

Run `build.bat`. It produces `dist\EnglishTutor.zip` (about 50 MB), which contains Python
and every library the app needs. The other person:

1. Unzips it anywhere, for example to `Documents\EnglishTutor`.
2. Double-clicks `EnglishTutor.exe` inside the unzipped folder. If Windows shows
   "Windows protected your PC", they click **More info → Run anyway**; the program isn't
   code-signed.
3. Enters their own Anthropic API key in Settings when asked. Don't build your key into the
   app; anyone with the file could extract it and use your account.

## How to use

The app runs in the system tray (the blue **영** icon).

| Action | Result |
| --- | --- |
| Highlight English text (or double-click a word), then press and release `Ctrl+Alt` together | Popup with the translation appears next to the cursor; your clipboard isn't changed |
| `Ctrl+Alt+T` | Also translates the current selection (works even when Ctrl+Alt translation is off) |
| **저장** next to a word or expression in the popup | Saves it to your vocabulary list |
| 📌 in the popup | Keeps the popup where you dragged it |
| **가- / 가+** in the popup, or `Ctrl` + mouse wheel over it | Makes the popup text smaller or larger |
| Drag the right edge, bottom edge or bottom-right corner of the popup | Resizes it; the size and text size are remembered |
| `Esc` or ✕ | Closes the popup |
| Tray icon → **내 단어장** (or double-click the icon) | Opens your vocabulary list: search, delete, open folder |
| Tray icon → **Ctrl+Alt로 번역하기** | Turns translation on `Ctrl+Alt` on or off |

## Where things are stored

| File | Location |
| --- | --- |
| Vocabulary | `Documents\EnglishTutor\vocabulary.json` and `vocabulary.csv` (opens in Excel); the folder can be changed in Settings |
| Settings | `%APPDATA%\EnglishTutor\settings.json` |
| Log (for troubleshooting) | `%APPDATA%\EnglishTutor\tutor.log` |

## How it works

- `english_tutor/selection.py` watches the keyboard globally. When you tap `Ctrl+Alt` with no
  other key (so shortcuts like `Ctrl+Alt+Del` don't count), or press `Ctrl+Alt+T`, it presses
  `Ctrl+C` itself, reads the text, then puts your previous clipboard text back. It skips
  terminal windows, where `Ctrl+C` would stop a running program.
- `english_tutor/translator.py` sends the text to Claude (`claude-opus-5-5` at low effort by
  default) and gets back structured JSON: translation, phrases, vocabulary. Results are cached
  so selecting the same sentence twice doesn't call the API again.
- `english_tutor/popup.py`, `windows.py` and `app.py` are the PySide6 UI and tray icon.
- `english_tutor/vocab.py` stores saved words as JSON and CSV.

## Notes

- Only one copy of the app runs at a time; starting it again shows a message instead.
- In Adobe Acrobat, use the Select tool (the arrow), not the Hand tool; the Hand tool doesn't select text.
- Some apps don't support copying (protected PDFs, images of text). Nothing will appear for those.
- If an image was on the clipboard, only text is put back after a translation.
- Model and effort level can be changed in Settings. Lower-cost models such as
  `claude-haiku-5-5` respond faster and cost less per translation.
