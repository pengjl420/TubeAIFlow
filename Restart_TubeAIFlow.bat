@echo off
setlocal

set "ROOT=%~dp0"

title TubeAIFlow Restart

echo.
echo ========================================
echo  TubeAIFlow - Restart
echo ========================================
echo.

echo Releasing local ports 18080 and 5173...
for %%P in (18080 5173) do (
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr /R /C:":%%P .*LISTENING"') do (
    echo Stopping process %%A on port %%P...
    taskkill /PID %%A /F >nul 2>nul
  )
)

echo.
echo Starting TubeAIFlow again...
call "%ROOT%Start_TubeAIFlow.bat"
