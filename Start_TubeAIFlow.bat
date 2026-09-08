@echo off
setlocal
title TubeAiFolw Launcher
set "ACTION=start"
if /I "%~1"=="--restart" set "ACTION=restart"
if /I "%~1"=="--stop" set "ACTION=stop"
if /I "%~1"=="--check" set "ACTION=check"
if /I "%~1"=="--repair" set "ACTION=repair"
if not "%~1"=="" if "%ACTION%"=="start" (
  echo Usage: Start_TubeAIFlow.bat [--restart ^| --stop ^| --check ^| --repair]
  exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Launch_TubeAiFolw.ps1" -Action %ACTION%
set "RESULT=%errorlevel%"
if not "%RESULT%"=="0" if "%~1"=="" pause
exit /b %RESULT%
