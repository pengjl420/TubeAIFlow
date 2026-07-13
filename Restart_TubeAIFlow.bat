@echo off
setlocal

set "ROOT=%~dp0"
set "BACKEND_DIR=%ROOT%backend"
set "BACKEND_LOCK=%BACKEND_DIR%\workspace\backend.lock"

title TubeAIFlow Restart

echo.
echo ========================================
echo  TubeAIFlow - Restart
echo ========================================
echo.

echo Stopping TubeAIFlow windows...
taskkill /FI "WINDOWTITLE eq TubeAIFlow Backend*" /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq TubeAIFlow Frontend*" /T /F >nul 2>nul

if exist "%BACKEND_LOCK%" (
  set /p BACKEND_PID=<"%BACKEND_LOCK%"
)
if defined BACKEND_PID (
  echo Stopping recorded backend process %BACKEND_PID%...
  taskkill /PID %BACKEND_PID% /T /F >nul 2>nul
)

echo Releasing default local ports 18080 and 5173...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%Stop_TubeAIFlow.ps1"

echo.
echo Starting TubeAIFlow again...
call "%ROOT%Start_TubeAIFlow.bat"
