@echo off
setlocal
cd /d "%~dp0"
call "%~dp0build-windows.bat"
exit /b %ERRORLEVEL%
