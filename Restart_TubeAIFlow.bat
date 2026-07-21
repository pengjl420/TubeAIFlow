@echo off
setlocal

set "ROOT=%~dp0"
title TubeAIFlow Restart

echo.
echo ========================================
echo  TubeAIFlow - Restart
echo ========================================
echo.

echo Stopping tracked processes and releasing local ports...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%Stop_TubeAIFlow.ps1"
if errorlevel 1 (
  echo [ERROR] Failed to stop the previous TubeAIFlow instance.
  pause
  exit /b 1
)

echo.
echo Starting TubeAIFlow again...
call "%ROOT%Start_TubeAIFlow.bat"
exit /b %errorlevel%
