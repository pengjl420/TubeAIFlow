@echo off
call "%~dp0Start_TubeAIFlow.bat" --restart %*
exit /b %errorlevel%
