@echo off
cd /d "%~dp0"
py -3.13 -m PyInstaller --noconfirm --clean --windowed --onedir --name KPNP-Live-Scoreboard --icon assets\app.ico --add-data "%CD%\assets;assets" --distpath pyinstaller-dist --workpath pyinstaller-build app\main.py
if errorlevel 1 exit /b 1

rem Windows supplies the Universal CRT and API-set forwarders. Bundling copies
rem from the build machine can make Qt fail on a different Windows release.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$runtimeDir = Join-Path $PWD 'pyinstaller-dist\KPNP-Live-Scoreboard\_internal'; Get-ChildItem -LiteralPath $runtimeDir -Filter 'api-ms-win-*.dll' -File | Remove-Item -Force; $ucrt = Join-Path $runtimeDir 'ucrtbase.dll'; if (Test-Path -LiteralPath $ucrt) { Remove-Item -LiteralPath $ucrt -Force }"
if errorlevel 1 exit /b 1
