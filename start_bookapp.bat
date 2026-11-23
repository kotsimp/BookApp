@echo off
title BookApp - Neural Document Translator & Audiobook Generator
echo ============================================================
echo   Starting BookApp (FastAPI + AI Polish + AudioBook Studio)
echo ============================================================
echo.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found in .venv.
    echo Please create the virtual environment first using:
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo Starting BookApp backend server on http://localhost:8000 ...
start /b "" ".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --timeout-graceful-shutdown 5

echo Waiting for server to initialize...
timeout /t 2 /nobreak >nul

echo Opening browser...
start http://127.0.0.1:8000

echo.
echo ============================================================
echo   BookApp is running! 
echo   Keep this window open while using the application.
echo   Press Ctrl+C or close this window to stop the server.
echo ============================================================
echo.

REM Keep terminal running to view live server logs if needed
pause
