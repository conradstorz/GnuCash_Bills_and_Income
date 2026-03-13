@echo off
title GnuCash Bills - Starting...

REM Check if server is already running on port 7432
netstat -ano | findstr ":7432" | findstr "LISTENING" >nul 2>&1

if %errorlevel% equ 0 (
    echo Server is already running on port 7432
    echo Opening browser to existing server...
    start http://localhost:7432
    echo.
    echo If the page doesn't load, close any existing server windows and try again.
    timeout /t 3 /nobreak >nul
    exit /b 0
)

echo Starting GnuCash Bills server on port 7432...
start /min "GnuCash Bills Server" cmd /k "cd /d D:\Users\Conrad\Documents\programming\GnuCash_bills_and_collections && uv run uvicorn bill_processor.web.app:app --port 7432"
echo Waiting for server to start...
timeout /t 3 /nobreak >nul

REM Verify server actually started
netstat -ano | findstr ":7432" | findstr "LISTENING" >nul 2>&1

if %errorlevel% equ 0 (
    echo Server started successfully!
    echo Opening browser...
    start http://localhost:7432
    echo Done. Server is running in the background (minimized in taskbar).
    echo Close the minimized console window to stop the server.
) else (
    echo ERROR: Server failed to start!
    echo Check the minimized window for error messages.
)

timeout /t 3 /nobreak >nul
