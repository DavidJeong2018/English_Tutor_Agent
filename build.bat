@echo off
rem Builds a standalone EnglishTutor folder (no Python needed) and zips it into dist\EnglishTutor.zip.
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv
    .venv\Scripts\python -m pip install -r requirements.txt
)
.venv\Scripts\python -m pip install -q pyinstaller
.venv\Scripts\python -m PyInstaller --noconfirm --clean --windowed --onedir ^
    --name EnglishTutor --icon assets\icon.ico main.py || exit /b 1
powershell -NoProfile -Command "Compress-Archive -Path dist\EnglishTutor -DestinationPath dist\EnglishTutor.zip -Force"
echo.
echo Built dist\EnglishTutor.zip
