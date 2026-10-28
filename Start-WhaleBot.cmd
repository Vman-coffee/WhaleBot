@echo off
setlocal
title WhaleBot
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start-WhaleBot.ps1"
if errorlevel 1 (
  echo.
  echo Startup failed. Review the message above.
  pause
  exit /b 1
)
endlocal
