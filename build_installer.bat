@echo off
cd /d "%~dp0"
call build_windows.bat
if errorlevel 1 exit /b 1
set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  where iscc >nul 2>nul
  if errorlevel 1 (
    echo Inno Setup 6 is required to compile the installer.
    echo Install it from https://jrsoftware.org/isdl.php then run this file again.
    pause
    exit /b 1
  )
  set "ISCC=iscc"
)
for /f %%v in ('py -3.13 -c "import sys;sys.path.insert(0,'app');from version import APP_VERSION;print(APP_VERSION)"') do set APP_VERSION=%%v
"%ISCC%" /DMyAppVersion=%APP_VERSION% installer\KPNP-Live-Scoreboard.iss
if errorlevel 1 pause
