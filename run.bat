@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Virtual environment not found: .venv\Scripts\python.exe
    pause
    exit /b 1
)
.venv\Scripts\python.exe -m app
if errorlevel 1 (
    echo Program exited with an error.
    pause
    exit /b 1
)
