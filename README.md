# KPNP Live Scoreboard v3.6

Native PySide6 Windows scoreboard with a separate broadcast output and operator panel.

## Install

Run `installer-output\KPNP-Live-Scoreboard-v3-Setup.exe`. The installer creates Start Menu and optional desktop shortcuts. Python is not required on the destination computer.

Version 3.6 adds verified in-app updates from this repository's GitHub Releases. The first update-enabled version must be installed normally. Later releases can be checked, downloaded and installed from the clearly visible **Application updates** section near the top of the operator dashboard.

Windows releases use Python 3.12 and the pinned, matched PySide6 6.8.3 runtime. Windows system runtime DLLs are deliberately not bundled. Each installation uses the compatible Universal CRT and API-set libraries supplied by its own Windows version, avoiding QtCore startup failures caused by runtime files copied from a newer build machine.

The installer also removes generated DLL, extension-module and package folders left by older Nuitka or PyInstaller versions before copying a new release. Application settings and KPNP connection details remain in the user's application-data folder.

The setup dashboard remembers the selected scoring program, Live/Virtual source, transport, host, port and output monitor. Live KPnP/TKDScoring and Daedo/TrueScore each use their own protocol decoder; Virtual Equipment mode remains available for safe testing.

## Run

1. Install 64-bit Python 3.14.
2. In this folder run `py -3.14 -m pip install -r requirements.txt`.
3. Double-click `run.bat`, or run `py -3.14 app\main.py`.

The output window scales while preserving the ultra-wide broadcast design. Use the searchable country selector to choose from all 249 ISO countries and territories. The matching real flag is downloaded automatically and cached locally for future/offline use. The operator can also edit names, scores, rounds and Gam-jeoms.

The **Virtual KPNP equipment** panel can connect/disconnect a simulated device, generate adjustable blue/red or simultaneous PSS hits, scores, Gam-jeoms, round wins, clock commands and round changes. Automatic Match produces a continuous realistic event stream. Every event travels through `KPNPListener`, updates the scoreboard automatically and appears in the raw event log. PSS impacts retain fast attack, peak hold and smooth decay. `build_windows.bat` creates a standalone application in `dist`.

## KPNP integration

`app/kpnp_listener.py` is the stable adapter boundary for a future decoded KPNP data feed. The virtual equipment already uses this boundary, so a real packet decoder can replace it without changing the scoreboard or match-state logic.

## Daedo / TrueScore integration

Select **Daedo/TrueScore** as the Program and **Live Daedo/TrueScore application** as the Source. The dashboard automatically selects UDP port **9988**.

In Daedo TkStrike Gen2, open **Configuration → External → General**. Under **External UDP Event Listeners**, add the IP address of the computer running this scoreboard and port **9988**, then save the TkStrike configuration. Back in the scoreboard, choose **Start live listener** before loading or starting the match in TkStrike.

The Daedo listener consumes TkStrike's native JSON match configuration and event datagrams. It updates athlete names, flags, match number, round, timer, running/timeout state, scores, Gam-jeoms, round wins and PSS hit strength, and resets the output when TkStrike reports that the match has finished. Raw Daedo datagrams are retained in `daedo_raw_capture.log` beside the existing KPnP capture for troubleshooting.

Run `build_windows.bat` with 64-bit Python 3.13 to rebuild the Qt-native standalone application using PyInstaller. Run `build_installer.bat` with Inno Setup 6 installed to rebuild the Setup executable.

## Publishing an update

1. Change `APP_VERSION` in `app/version.py`.
2. Commit the tested source to `main`.
3. Create and push a matching tag, for example `v3.6.1`.
4. GitHub Actions builds the standalone app, portable ZIP, checksums and installer.
5. The workflow publishes those files to a GitHub Release.

Installed applications query the latest public release, verify the installer using GitHub's SHA-256 asset digest, and run it silently after the operator approves the update. Updates are blocked while the match clock is running. Local settings and KPNP connection details remain in the user's application-data folder.

Generated build folders, installers, local captures, Python caches and rendered design checks are excluded from source control. Release binaries belong in GitHub Releases rather than the source tree.
