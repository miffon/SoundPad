@echo off
setlocal

cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo uv was not found. Please install uv first:
    echo https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)

uv run python main.py
if errorlevel 1 (
    echo.
    echo SoundPad exited with an error.
    pause
)
