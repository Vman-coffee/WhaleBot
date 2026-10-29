@echo off
setlocal
title WhaleBot - Stop
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Stop-WhaleBot.ps1"
if errorlevel 1 (
  echo.
  echo Shutdown failed. Review the message above.
  pause
  exit /b 1
)
endlocal
