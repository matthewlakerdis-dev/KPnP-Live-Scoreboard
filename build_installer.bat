@echo off
cd /d "%~dp0"
call build_windows.bat
if errorlevel 1 exit /b 1
where iscc >nul 2>nul
if errorlevel 1 (
  echo Inno Setup 6 is required to compile the installer.
  echo Install it from https://jrsoftware.org/isdl.php then run this file again.
  pause
  exit /b 1
)
iscc installer\KPNP-Live-Scoreboard.iss
if errorlevel 1 pause
