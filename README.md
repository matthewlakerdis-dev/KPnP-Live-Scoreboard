# KPNP Live Scoreboard v3

Native PySide6 Windows scoreboard with a separate broadcast output and operator panel.

## Install

Run `installer-output\KPNP-Live-Scoreboard-v3-Setup.exe`. The installer creates Start Menu and optional desktop shortcuts. Python is not required on the destination computer.

The setup dashboard remembers the selected Live/Virtual source, transport, host, port and output monitor. Live KPNP mode is reserved for the real protocol decoder once genuine KPNP traffic has been captured; Virtual Equipment mode is fully operational now.

## Run

1. Install 64-bit Python 3.14.
2. In this folder run `py -3.14 -m pip install -r requirements.txt`.
3. Double-click `run.bat`, or run `py -3.14 app\main.py`.

The output window scales while preserving the ultra-wide broadcast design. Use the searchable country selector to choose from all 249 ISO countries and territories. The matching real flag is downloaded automatically and cached locally for future/offline use. The operator can also edit names, scores, rounds and Gam-jeoms.

The **Virtual KPNP equipment** panel can connect/disconnect a simulated device, generate adjustable blue/red or simultaneous PSS hits, scores, Gam-jeoms, round wins, clock commands and round changes. Automatic Match produces a continuous realistic event stream. Every event travels through `KPNPListener`, updates the scoreboard automatically and appears in the raw event log. PSS impacts retain fast attack, peak hold and smooth decay. `build_windows.bat` creates a standalone application in `dist`.

## KPNP integration

`app/kpnp_listener.py` is the stable adapter boundary for a future decoded KPNP data feed. The virtual equipment already uses this boundary, so a real packet decoder can replace it without changing the scoreboard or match-state logic.

Run `build_windows.bat` with 64-bit Python 3.13 to rebuild the Qt-native standalone application using Nuitka. Run `build_installer.bat` with Inno Setup 6 installed to rebuild the Setup executable.
