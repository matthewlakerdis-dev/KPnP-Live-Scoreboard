@echo off
cd /d "%~dp0"
py -3.13 -m nuitka --standalone --enable-plugin=pyside6 --windows-console-mode=disable --windows-icon-from-ico=assets\app.ico --include-data-dir=assets=assets --output-dir=nuitka-dist --output-filename=KPNP-Live-Scoreboard.exe --assume-yes-for-downloads app\main.py
if errorlevel 1 pause
