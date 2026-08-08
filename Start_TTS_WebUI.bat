@echo off
setlocal
set "ENGINE=%~1"
if not defined ENGINE (
  echo Usage: Start_TTS_WebUI.bat index_tts ^| moss_tts ^| cosyvoice ^| qwen3_tts
  exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start_TTSWebUI.ps1" -Engine "%ENGINE%"
exit /b %errorlevel%
