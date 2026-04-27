@echo off
setlocal enabledelayedexpansion
title GnuCash Bills - Starting...

set PROJ=D:\Users\Conrad\Documents\programming\GnuCash_bills_and_collections
set LOG=%PROJ%\logs\launcher.log

echo. >> "%LOG%"
echo ============================================================ >> "%LOG%"
echo [%date% %time%] Launcher started >> "%LOG%"

echo Checking if GnuCash Bills server is already running on port 7432...
echo [%date% %time%] Checking if server already running... >> "%LOG%"
curl -s -o nul -w "%%{http_code}" http://localhost:7432/api/status >> "%LOG%" 2>&1
set CURL_RESULT=!errorlevel!
echo  (curl errorlevel: !CURL_RESULT!) >> "%LOG%"
if !CURL_RESULT! equ 0 (
    echo Server is already running. Opening browser...
    echo [%date% %time%] Server already running - skipping build, opening browser >> "%LOG%"
    start http://localhost:7432
    timeout /t 2 /nobreak >nul
    exit /b 0
)

echo [%date% %time%] Server not running (curl errorlevel !CURL_RESULT!) - proceeding to build >> "%LOG%"
echo Building frontend...
echo [%date% %time%] Starting frontend build (npm run build)... >> "%LOG%"
cd /d %PROJ%\frontend
call npm run build >> "%LOG%" 2>&1
set BUILD_RESULT=!errorlevel!
echo [%date% %time%] Frontend build finished - errorlevel: !BUILD_RESULT! >> "%LOG%"
if !BUILD_RESULT! neq 0 (
    echo ERROR: Frontend build failed.
    echo [%date% %time%] ERROR: Frontend build failed >> "%LOG%"
    pause
    exit /b 1
)
cd /d %PROJ%

echo Starting GnuCash Bills server on port 7432...
echo [%date% %time%] Launching server process... >> "%LOG%"
start "GnuCash Bills Server" cmd /c "cd /d %PROJ% && uv run uvicorn bill_processor.web.app:app --port 7432 & echo. & echo Server stopped. Closing in 3 seconds... & timeout /t 3 /nobreak >nul"

echo Waiting for server to start...
echo [%date% %time%] Polling for server readiness (max 30s)... >> "%LOG%"
set /a max_wait_seconds=30
set /a elapsed=0
:wait_loop
curl -s -o nul -w "%%{http_code}" http://localhost:7432/api/status >> "%LOG%" 2>&1
set POLL_RESULT=!errorlevel!
echo  poll[!elapsed!s] curl errorlevel: !POLL_RESULT! >> "%LOG%"
if !POLL_RESULT! equ 0 goto server_ready
if !elapsed! geq !max_wait_seconds! goto server_failed
timeout /t 1 /nobreak >nul
set /a elapsed+=1
goto wait_loop

:server_failed
echo ERROR: Server failed to start after 30 seconds.
echo [%date% %time%] ERROR: Server failed after !elapsed! poll attempts >> "%LOG%"
pause
exit /b 1

:server_ready
echo Opening browser...
echo [%date% %time%] Server ready after !elapsed!s - opening browser >> "%LOG%"
start http://localhost:7432
echo.
echo SUCCESS: Server is running in a separate console window.
echo [%date% %time%] Launcher complete >> "%LOG%"
echo This window will close in 20 seconds...
timeout /t 20 >nul
