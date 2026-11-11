@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Phantom-AI 5.1.13 Windows Builder
echo.
echo =================================================
echo       PHANTOM-AI 5.1.13 WINDOWS BUILDER
echo =================================================
echo.
set "BUILDER=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%BUILDER%" set "BUILDER=powershell.exe"
"%BUILDER%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-windows.ps1"
set "BUILD_EXIT=%ERRORLEVEL%"
echo.
if not "%BUILD_EXIT%"=="0" (
  echo Phantom-AI build failed. The PowerShell output above contains the exact failed step.
) else (
  echo Phantom-AI build completed successfully.
)
echo.
pause
exit /b %BUILD_EXIT%
