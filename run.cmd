@echo off
rem Same as run.ps1, but works even when PowerShell script execution is disabled.
rem   run mise -Dual   |   run mise -Dual -Phone   |   run mise -Engine ollama
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
