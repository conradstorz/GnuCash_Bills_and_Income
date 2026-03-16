@echo off
title GnuCash Bills - Starting...
echo Checking if GnuCash Bills server is already running on port 7432...
netstat -ano | findstr :7432 | findstr LISTENING >nul 2>&1
if %errorlevel% equ 0 (
    echo Server is already running. Opening browser...
    start http://localhost:7432
    echo Done.
    timeout /t 2 /nobreak >nul
    exit /b 0
)

echo Starting GnuCash Bills server on port 7432...
start "GnuCash Bills Server" cmd /c "cd /d D:\Users\Conrad\Documents\programming\GnuCash_bills_and_collections && uv run uvicorn bill_processor.web.app:app --port 7432 & echo. & echo Server stopped. Closing window in 3 seconds... & timeout /t 3 /nobreak >nul"
echo Waiting for server to start...
set /a attempts=0
:wait_loop
timeout /t 1 /nobreak >nul
set /a attempts+=1
netstat -ano | findstr :7432 | findstr LISTENING >nul 2>&1
if %errorlevel% equ 0 goto server_ready
if %attempts% lss 15 goto wait_loop

echo ERROR: Server failed to start on port 7432 after 15 seconds.
echo Check the server console window for errors.
pause
exit /b 1

:server_ready

echo Opening browser...
start http://localhost:7432
echo.
echo SUCCESS: Server is running in a separate console window.
echo Close the server console window to stop the application.
echo.
echo This window will close automatically in 20 seconds...
timeout /t 20 >nul
