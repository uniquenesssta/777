@echo off
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0host.ps1" -Operation inventory
if errorlevel 1 echo Inventory failed. Check logs in this folder.
echo.
echo Log location: %~dp0logs
pause
