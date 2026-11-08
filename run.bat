@echo off
rem Starts English Tutor without a console window.
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv
    .venv\Scripts\python -m pip install -r requirements.txt
)
start "" .venv\Scripts\pythonw.exe main.py
