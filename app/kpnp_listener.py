"""UDP capture and normalization boundary for KPNP scoring data."""

from datetime import datetime
import os
from pathlib import Path
import socket
import threading

import pycountry
from PySide6.QtCore import QObject, Signal


# KPNP uses international sporting/IOC codes. Most match ISO alpha-3, but
# these differ and must be translated before pycountry can resolve a flag.
SPORT_CODE_TO_ISO2 = {
    "ALG":"DZ", "ANG":"AO", "ANT":"AG", "ARU":"AW", "ASA":"AS",
    "BAH":"BS", "BAN":"BD", "BAR":"BB", "BER":"BM", "BHU":"BT",
    "BIZ":"BZ", "BOT":"BW", "BRN":"BH", "BRU":"BN",
    "BUL":"BG", "BUR":"BF", "CAM":"KH", "CAY":"KY", "CGO":"CG",
    "CHA":"TD", "CHI":"CL", "CRC":"CR", "CRO":"HR", "DEN":"DK",
    "ESA":"SV", "FIJ":"FJ", "GAM":"GM", "GBR":"GB", "GBS":"GW", "GEQ":"GQ",
    "GER":"DE", "GRE":"GR", "GRN":"GD", "GUA":"GT", "GUI":"GN",
    "GUM":"GU", "HAI":"HT", "HON":"HN", "INA":"ID", "IRI":"IR",
    "ISV":"VI", "IVB":"VG", "KSA":"SA", "KUW":"KW", "LAT":"LV",
    "LBA":"LY", "LES":"LS", "MAD":"MG", "MAS":"MY", "MAW":"MW",
    "MGL":"MN", "MON":"MC", "MRI":"MU", "MTN":"MR", "MYA":"MM", "NCA":"NI",
    "NED":"NL", "NEP":"NP", "NGR":"NG", "NIG":"NE", "OMA":"OM",
    "PAR":"PY", "PHI":"PH", "PLE":"PS", "POR":"PT", "PUR":"PR",
    "RSA":"ZA", "SAM":"WS", "SEY":"SC", "SIN":"SG", "SKN":"KN", "SLO":"SI", "SOL":"SB",
    "SRI":"LK", "SUD":"SD", "SUI":"CH", "TAN":"TZ", "TGA":"TO", "TOG":"TG",
    "TPE":"TW", "UAE":"AE", "URU":"UY", "VAN":"VU", "VIE":"VN",
    "VIN":"VC", "ZAM":"ZM", "ZIM":"ZW",
}


class KPNPListener(QObject):
    packet = Signal(dict)
    status = Signal(str)
    program_name = "KPNP"
    raw_event_name = "raw_kpnp"
    capture_filename = "kpnp_raw_capture.log"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._socket = None
        self._thread = None
        self._peer = None
        self._current_round = None
        data_root = Path(os.environ.get("APPDATA", Path.home())) / "KPNP Scoreboard"
        data_root.mkdir(parents=True, exist_ok=True)
        self.capture_path = data_root / self.capture_filename

    def start_udp(self, host="0.0.0.0", port=8056):
        self.stop()
        self._peer = None
        self._running = True
        self._thread = threading.Thread(target=self._listen_udp, args=(host or "0.0.0.0", int(port)), daemon=True)
        self._thread.start()

    def start_tcp(self, host="0.0.0.0", port=8056):
        """Accept the outbound TCP/IP connection created by KPNP OVR."""
        self.stop()
        self._peer = None
        self._running = True
        self._thread = threading.Thread(target=self._listen_tcp, args=(host or "0.0.0.0", int(port)), daemon=True)
        self._thread.start()

    def _listen_tcp(self, host, port):
        server = None
        connection = None
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((host, port))
            server.listen(1)
            server.settimeout(1.0)
            self._socket = server
            self.status.emit(f"Waiting for {self.program_name} TCP/IP on {host}:{port}")
            while self._running:
                if connection is None:
                    try:
                        connection, address = server.accept()
                        connection.settimeout(1.0)
                        self._peer = address[0]
                        self.status.emit(f"{self.program_name} connected from {address[0]}")
                    except socket.timeout:
                        continue
                try:
                    data = connection.recv(65535)
                    if not data:
                        connection.close()
                        connection = None
                        self.status.emit(f"Waiting for {self.program_name} TCP/IP on {host}:{port}")
                        continue
                except socket.timeout:
                    continue
                except OSError:
                    if not self._running:
                        break
                    connection = None
                    continue
                text = data.decode(errors="ignore").strip().strip("'\"")
                for message in text.splitlines() or (text,):
                    message = message.strip()
                    if message:
                        self._capture(message, address)
                        self._decode(message)
        except OSError as error:
            self.status.emit(f"{self.program_name} TCP listener error: {error}")
        finally:
            for item in (connection, server):
                if item is not None:
                    try:
                        item.close()
                    except OSError:
                        pass
            self._socket = None
            self._running = False

    def _listen_udp(self, host, port):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind((host, port))
            sock.settimeout(1.0)
            self._socket = sock
            self.status.emit(f"Listening for {self.program_name} on UDP {host}:{port}")
            while self._running:
                try:
                    data, address = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                except OSError:
                    if not self._running:
                        break
                    raise
                text = data.decode(errors="ignore").strip().strip("'\"")
                for message in text.splitlines() or (text,):
                    message = message.strip()
                    if message:
                        self._capture(message, address)
                        self._decode(message)
        except OSError as error:
            self.status.emit(f"{self.program_name} UDP listener error: {error}")
        finally:
            if self._socket is not None:
                try:
                    self._socket.close()
                except OSError:
                    pass
            self._socket = None
            self._running = False

    def _capture(self, message, address):
        if self._peer != address[0]:
            self._peer = address[0]
            self.status.emit(f"{self.program_name} connected from {address[0]}")
        timestamp = datetime.now().isoformat(timespec="milliseconds")
        with self.capture_path.open("a", encoding="utf-8") as capture:
            capture.write(f"{timestamp}\t{address[0]}:{address[1]}\t{message}\n")
        self.packet.emit({"event": self.raw_event_name, "message": message, "source": address[0]})

    def _decode(self, message):
        parts = [part.strip() for part in message.split(";")]
        command = parts[0].lower() if parts else ""
        if command == "pre" and len(parts) > 1 and parts[1].lower() == "fightloaded":
            self._current_round = 1
            self.packet.emit({
                "event": "state", "blue_score": 0, "red_score": 0,
                "blue_gamjeom": 0, "red_gamjeom": 0,
                "blue_rounds": 0, "red_rounds": 0,
                "blue_pss": 0.0, "red_pss": 0.0,
                "round": 1, "running": False, "timeout_active": False,
            })
        elif command == "at1" and "at2" in parts:
            split = parts.index("at2")
            blue = parts[1:split]
            red = parts[split + 1:]
            blue_first = blue[0] if blue else ""
            blue_last = blue[1] if len(blue) > 1 and blue[1].casefold() != blue_first.casefold() else ""
            red_first = red[0] if red else ""
            red_last = red[1] if len(red) > 1 and red[1].casefold() != red_first.casefold() else ""
            update = {
                "event": "state",
                "blue_first": blue_first, "blue_last": blue_last,
                "red_first": red_first, "red_last": red_last,
            }
            for side, fields in (("blue", blue), ("red", red)):
                for raw_country in fields[2:]:
                    if not raw_country:
                        continue
                    code = raw_country.strip().upper()
                    code = SPORT_CODE_TO_ISO2.get(code,code)
                    if code in ("AIN","KOS"):
                        update[f"{side}_alpha2"] = ""
                        update[f"{side}_country"] = code
                        update[f"{side}_nation"] = code
                        break
                    country = None
                    try:
                        country = pycountry.countries.lookup(code)
                    except LookupError:
                        pass
                    if country is not None:
                        update[f"{side}_alpha2"] = country.alpha_2
                        update[f"{side}_country"] = country.alpha_3
                        update[f"{side}_nation"] = country.name.upper()
                        break
            self.packet.emit(update)
        elif command == "mch" and len(parts) > 1:
            self.packet.emit({"event": "state", "match_number": parts[1]})
            # KPNP places the configured round duration immediately before
            # its cntDown/cntUp marker in the match-loaded packet.
            for marker in ("cntDown", "cntUp"):
                if marker in parts:
                    index = parts.index(marker)
                    if index and parts[index - 1].isdigit():
                        self.packet.emit({"event": "state", "seconds": int(parts[index - 1]), "running": False})
                    break
        elif command == "wrd":
            winners = []
            for index, value in enumerate(parts):
                if value.lower().startswith("rd") and index + 1 < len(parts):
                    winners.append(parts[index + 1].lower())
            blue_values = {"1", "b", "blue", "chung"}
            red_values = {"2", "r", "red", "hong"}
            self.packet.emit({
                "event": "state",
                "blue_rounds": sum(value in blue_values for value in winners),
                "red_rounds": sum(value in red_values for value in winners),
            })
        elif command == "sc1" and "sc2" in parts:
            split = parts.index("sc2")
            try:
                blue_score = int(parts[1])
                red_score = int(parts[split + 1])
                self.packet.emit({"event": "state", "blue_score": blue_score, "red_score": red_score})
            except (ValueError, IndexError):
                pass
        elif command == "wg1" and "wg2" in parts:
            split = parts.index("wg2")
            try:
                blue_gamjeom = int(parts[1])
                red_gamjeom = int(parts[split + 1])
                self.packet.emit({"event": "state", "blue_gamjeom": blue_gamjeom, "red_gamjeom": red_gamjeom})
            except (ValueError, IndexError):
                pass
        elif command == "clk" and len(parts) > 1:
            try:
                minutes, seconds = (int(value) for value in parts[1].split(":", 1))
                update = {"event": "state", "seconds": minutes * 60 + seconds}
                if len(parts) > 2 and parts[2].lower() in ("start", "stop"):
                    update["running"] = parts[2].lower() == "start"
                    if parts[2].lower() == "start": update["timeout_active"] = False
                if len(parts) > 2 and parts[2].lower() in ("break", "rest", "timeout", "time out"):
                    update.update(running=False, timeout_active=True)
                self.packet.emit(update)
            except (ValueError, TypeError):
                pass
        elif command == "rnd" and len(parts) > 1:
            try:
                round_number = max(1, min(3, int(parts[1])))
                update = {"event": "state", "round": round_number, "timeout_active": False}
                if self._current_round is not None and round_number != self._current_round:
                    update.update(
                        blue_score=0, red_score=0,
                        blue_gamjeom=0, red_gamjeom=0,
                        blue_pss=0.0, red_pss=0.0,
                        running=False,
                    )
                self._current_round = round_number
                self.packet.emit(update)
            except ValueError:
                pass
        elif command in ("brk", "break", "rest", "tmo", "timeout"):
            update = {"event": "state", "running": False, "timeout_active": True}
            for value in parts[1:]:
                try:
                    if ":" in value:
                        minutes, seconds = (int(piece) for piece in value.split(":", 1))
                        update["seconds"] = minutes * 60 + seconds
                        break
                    if value.isdigit():
                        update["seconds"] = int(value)
                        break
                except ValueError:
                    pass
            self.packet.emit(update)
        elif command == "wmh":
            self.packet.emit({"event": "result", "fields": parts[1:]})
            self.packet.emit({"event": "fight_finished"})
        elif command == "win" or message.lower().startswith("win'"):
            upper = message.upper()
            winner = "red" if "RED" in upper else "blue" if "BLUE" in upper else ""
            self.packet.emit({"event": "state", "running": False})
            self.packet.emit({"event": "winner", "side": winner, "message": message})
            self.packet.emit({"event": "fight_finished"})

    def stop(self):
        self._running = False
        self._peer = None
        sock = self._socket
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        self.status.emit(f"{self.program_name} listener stopped")

    def feed(self, packet):
        """Accept a normalized packet from virtual equipment or a decoder."""
        if isinstance(packet, dict):
            self.packet.emit(packet)
