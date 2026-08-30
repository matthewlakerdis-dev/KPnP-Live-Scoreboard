from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QApplication

from version import APP_VERSION, LATEST_RELEASE_API, LATEST_RELEASE_MANIFEST


def version_tuple(value: str) -> tuple[int, ...]:
    clean = value.strip().lower().removeprefix("v").split("-", 1)[0]
    try:
        return tuple(int(part) for part in clean.split("."))
    except ValueError:
        return (0,)


class UpdateManager(QObject):
    status = Signal(str)
    available = Signal(str, str)
    current = Signal(str)
    progress = Signal(int)
    ready = Signal(str)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.network = QNetworkAccessManager(self)
        self.asset = None
        self.version = ""
        self.download_path = None

    def _request(self, url: str) -> QNetworkRequest:
        request = QNetworkRequest(QUrl(url))
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute,QNetworkRequest.NoLessSafeRedirectPolicy)
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"X-GitHub-Api-Version", b"2022-11-28")
        request.setRawHeader(b"User-Agent", b"KPNP-Live-Scoreboard-Updater")
        request.setRawHeader(b"Cache-Control", b"no-cache")
        return request

    def check(self):
        self.status.emit("Checking for updates…")
        self._check_url(LATEST_RELEASE_MANIFEST,True)

    def _check_url(self,url: str,allow_api_fallback: bool,redirects: int=0):
        reply = self.network.get(self._request(url))
        reply.finished.connect(lambda:self._checked(reply,allow_api_fallback,redirects))

    def _checked(self,reply: QNetworkReply,allow_api_fallback: bool=False,redirects: int=0):
        try:
            redirect = reply.attribute(QNetworkRequest.RedirectionTargetAttribute)
            if redirect and redirect.isValid():
                if redirects >= 5:
                    raise RuntimeError("GitHub returned too many redirects")
                target = reply.url().resolved(redirect).toString()
                self._check_url(target,allow_api_fallback,redirects+1)
                return
            if reply.error() != QNetworkReply.NoError:
                if allow_api_fallback:
                    self._check_url(LATEST_RELEASE_API,False)
                    return
                status=reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
                if status in (403,429):
                    raise RuntimeError("GitHub is temporarily rate-limiting update checks; try again later or download the installer from GitHub Releases")
                raise RuntimeError(reply.errorString())
            payload = bytes(reply.readAll())
            try:
                release = json.loads(payload)
            except (json.JSONDecodeError,UnicodeDecodeError):
                if allow_api_fallback:
                    self._check_url(LATEST_RELEASE_API,False)
                    return
                raise RuntimeError("GitHub returned unreadable update information; please try again")
            self._use_release(release)
        except Exception as exc:
            self.failed.emit(f"Update check failed: {exc}")
        finally:
            reply.deleteLater()

    def _use_release(self,release: dict):
        tag = str(release.get("tag_name", ""))
        if not tag:
            raise RuntimeError("The update information did not contain a version")
        if version_tuple(tag) <= version_tuple(APP_VERSION):
            self.asset = None
            self.current.emit(f"Version {APP_VERSION} is up to date")
            return
        assets = release.get("assets") or []
        asset = next((item for item in assets if str(item.get("name", "")).lower().endswith("setup.exe")), None)
        if not asset:
            raise RuntimeError("The latest release does not contain a Windows installer")
        self.asset = asset
        self.version = tag.removeprefix("v")
        notes = str(release.get("body") or "No release notes were provided.")
        self.available.emit(self.version, notes)

    def download(self):
        if not self.asset:
            self.failed.emit("Check for updates before downloading")
            return
        url = str(self.asset.get("browser_download_url", ""))
        parsed = urlparse(url)
        if parsed.scheme != "https" or not (parsed.hostname == "github.com" or str(parsed.hostname).endswith(".githubusercontent.com")):
            self.failed.emit("GitHub returned an invalid update address")
            return
        folder = Path(tempfile.gettempdir()) / "KPNP-Live-Scoreboard-Updates"
        folder.mkdir(parents=True, exist_ok=True)
        self.download_path = folder / str(self.asset.get("name", "KPNP-Live-Scoreboard-Setup.exe"))
        self.status.emit(f"Downloading version {self.version}…")
        self._download_url(url)

    def _download_url(self,url: str,redirects: int=0):
        reply = self.network.get(self._request(url))
        reply.downloadProgress.connect(lambda received,total:self.progress.emit(int(received*100/total) if total>0 else 0))
        reply.finished.connect(lambda: self._downloaded(reply,redirects))

    def _downloaded(self, reply: QNetworkReply,redirects: int=0):
        try:
            redirect = reply.attribute(QNetworkRequest.RedirectionTargetAttribute)
            if redirect and redirect.isValid():
                if redirects >= 5:
                    raise RuntimeError("GitHub returned too many redirects")
                target = reply.url().resolved(redirect).toString()
                self._download_url(target,redirects+1)
                return
            if reply.error() != QNetworkReply.NoError:
                raise RuntimeError(reply.errorString())
            data = bytes(reply.readAll())
            expected = str(self.asset.get("digest") or "")
            if not expected.startswith("sha256:"):
                raise RuntimeError("The release is missing its SHA-256 verification value")
            actual = hashlib.sha256(data).hexdigest()
            if actual.casefold() != expected.split(":", 1)[1].casefold():
                raise RuntimeError("The downloaded update failed verification")
            self.download_path.write_bytes(data)
            self.ready.emit(str(self.download_path))
        except Exception as exc:
            self.failed.emit(f"Update download failed: {exc}")
        finally:
            reply.deleteLater()

    def install(self):
        if not self.download_path or not self.download_path.exists():
            self.failed.emit("The verified update file is no longer available")
            return
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen([
            str(self.download_path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
            "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"
        ], close_fds=True, creationflags=flags)
        self.status.emit("Installing update and restarting…")
        QTimer.singleShot(350, QApplication.quit)
