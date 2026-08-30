@echo off
cd /d "%~dp0"
py -3.13 -m PyInstaller --noconfirm --clean --windowed --onedir --name KPNP-Live-Scoreboard --icon assets\app.ico --add-data "%CD%\assets;assets" --distpath pyinstaller-dist --workpath pyinstaller-build app\main.py
if errorlevel 1 pause
