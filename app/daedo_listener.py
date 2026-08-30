"""Daedo TkStrike/TrueScore UDP event listener and scoreboard normalizer."""

import json
import math
import re

import pycountry

from kpnp_listener import KPNPListener, SPORT_CODE_TO_ISO2


class DaedoListener(KPNPListener):
    """Receive the JSON datagrams emitted by TkStrike's UDP event listener.

    TkStrike sends either a MatchConfigurationDto (when a match is loaded) or
    a TkStrikeEventDto (for live match activity).  Both are plain UTF-8 JSON.
    The inherited socket code keeps UDP/TCP capture behaviour consistent with
    the existing KPnP listener while this class owns Daedo-specific decoding.
    """

    program_name = "Daedo"
    raw_event_name = "raw_daedo"
    capture_filename = "daedo_raw_capture.log"

    def _decode(self, message):
        payload = self._json_payload(message)
        if payload is None:
            # Also accept TkStrike RT Broadcast text if a venue is already
            # configured for that interface. UDP JSON remains the preferred
            # and complete integration path.
            self._decode_rt_broadcast(message)
            return

        payload = self._unwrap(payload)
        if not isinstance(payload, dict):
            return
        if self._pick(payload, "eventType", "event_type") is not None:
            self._decode_event(payload)
        elif any(key in payload for key in ("blueAthlete", "redAthlete", "matchConfiguration")):
            self._decode_match(payload)

    @staticmethod
    def _json_payload(message):
        cleaned = message.replace("\x00", "").lstrip("\ufeff").strip()
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if 0 <= start < end:
                try:
                    return json.loads(cleaned[start:end + 1])
                except json.JSONDecodeError:
                    pass
        return None

    @staticmethod
    def _unwrap(payload):
        for key in ("tkStrikeEvent", "event", "matchConfiguration", "data"):
            nested = payload.get(key) if isinstance(payload, dict) else None
            if isinstance(nested, dict):
                return nested
        return payload

    @staticmethod
    def _pick(payload, *names, default=None):
        for name in names:
            if name in payload and payload[name] is not None:
                return payload[name]
        return default

    @staticmethod
    def _integer(value, default=None):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _decode_match(self, payload):
        payload = self._unwrap(payload)
        blue = payload.get("blueAthlete") or {}
        red = payload.get("redAthlete") or {}
        update = {
            "event": "state",
            "blue_score": 0, "red_score": 0,
            "blue_gamjeom": 0, "red_gamjeom": 0,
            "blue_rounds": 0, "red_rounds": 0,
            "blue_pss": 0.0, "red_pss": 0.0,
            "round": 1, "running": False, "timeout_active": False,
        }
        match_number = self._pick(payload, "matchNumber", "match_number")
        if match_number not in (None, ""):
            update["match_number"] = str(match_number)
        self._athlete_fields(update, "blue", blue)
        self._athlete_fields(update, "red", red)
        rounds = payload.get("roundsConfig") or {}
        duration = self._pick(rounds, "roundTime", "roundDuration", "duration")
        seconds = self._time_seconds(duration)
        if seconds is None:
            minutes = self._integer(rounds.get("roundTimeMinutes"), 0)
            remainder = self._integer(rounds.get("roundTimeSeconds"), 0)
            if minutes or remainder:
                seconds = minutes * 60 + remainder
        if seconds is not None:
            update["seconds"] = seconds
        self._current_round = 1
        self.packet.emit(update)

    def _athlete_fields(self, update, side, athlete):
        if not isinstance(athlete, dict):
            return
        display = str(self._pick(athlete, "scoreboardName", "tvName", "printName", default="") or "").strip()
        given = str(self._pick(athlete, "givenName", "preferredGivenName", default="") or "").strip()
        family = str(self._pick(athlete, "familyName", "preferredFamilyName", default="") or "").strip()
        # scoreboardName is TkStrike's already-formatted broadcast value. Keep
        # it intact and do not append the separate family name a second time.
        update[f"{side}_first"] = display or given
        update[f"{side}_last"] = "" if display else family
        code = str(self._pick(athlete, "flagAbbreviation", "countryCode", "noc", default="") or "").upper().strip()
        if not code:
            return
        iso = SPORT_CODE_TO_ISO2.get(code, code)
        try:
            country = pycountry.countries.lookup(iso)
        except LookupError:
            update[f"{side}_country"] = code
            update[f"{side}_nation"] = str(self._pick(athlete, "flagName", default=code)).upper()
            return
        update[f"{side}_alpha2"] = country.alpha_2
        update[f"{side}_country"] = country.alpha_3
        update[f"{side}_nation"] = country.name.upper()

    def _decode_event(self, payload):
        event_type = str(self._pick(payload, "eventType", "event_type", default="")).upper()
        update = {"event": "state"}
        mapping = {
            "bluePoints": "blue_score", "redPoints": "red_score",
            "bluePenalties": "blue_gamjeom", "redPenalties": "red_gamjeom",
            "blueRoundWins": "blue_rounds", "redRoundWins": "red_rounds",
        }
        for source, target in mapping.items():
            value = self._integer(payload.get(source))
            if value is not None:
                update[target] = value
        match_number = self._pick(payload, "matchNumber", "match_number")
        if match_number not in (None, ""):
            update["match_number"] = str(match_number)
        round_number = self._integer(self._pick(payload, "roundNumber", "round_number"))
        if round_number is not None:
            update["round"] = max(1, min(3, round_number))
            self._current_round = update["round"]
        seconds = self._event_seconds(payload)
        if seconds is not None:
            update["seconds"] = seconds

        if event_type == "START_MATCH":
            update.update(running=False, timeout_active=False)
        elif event_type in ("START_ROUND", "RESUME"):
            update.update(running=True, timeout_active=False)
        elif event_type in ("TIMEOUT", "KYE_SHI", "DOCTOR", "MEETING"):
            update.update(running=False, timeout_active=True)
        elif event_type in ("END_ROUND", "MATCH_FINISHED", "DOCTOR_QUIT"):
            update.update(running=False, timeout_active=False)
        if len(update) > 1:
            self.packet.emit(update)

        if event_type.endswith(("_BODY_HIT", "_HEAD_HIT")):
            side = "blue" if event_type.startswith("BLUE_") else "red"
            strength = self._integer(self._pick(payload, "hitlevel", "hitLevel"), 0)
            self.packet.emit({"event": "pss_hit", "side": side, "strength": max(0, min(100, strength))})
        if event_type == "MATCH_FINISHED":
            self.packet.emit({
                "event": "result",
                "fields": [self._pick(payload, "matchWinner", default=""), self._pick(payload, "matchFinalDecision", default="")],
            })
            self.packet.emit({"event": "fight_finished"})

    def _event_seconds(self, payload):
        text = self._pick(payload, "roundTimestampStr", "roundTime", "time")
        seconds = self._time_seconds(text)
        if seconds is not None:
            return seconds
        raw = self._integer(self._pick(payload, "roundTimestamp", "round_timestamp"))
        if raw is None:
            return None
        # TkStrike's DTO uses milliseconds; accepting seconds as well makes
        # captures from older TrueScore builds harmless.
        return max(0, raw // 1000 if raw > 3600 else raw)

    @staticmethod
    def _time_seconds(value):
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            value = int(value)
            return max(0, value // 1000 if value > 3600 else value)
        text = str(value).strip()
        try:
            parts = text.split(":")
            if len(parts) == 2:
                # TkStrike's real countdown format is MM:SS.mmm. Round up the
                # fractional second so 01:59.999 remains 2:00 on a seconds-only
                # broadcast clock, matching TkStrike's visible timer.
                return max(0, int(math.ceil(int(parts[0]) * 60 + float(parts[1]))))
            if len(parts) == 3:
                return max(0, int(math.ceil(int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2]))))
            return max(0, int(math.ceil(float(text))))
        except ValueError:
            matches = re.findall(r"\d+", text)
            return int(matches[0]) if matches else None

    def _decode_rt_broadcast(self, message):
        printable = "".join(char for char in message if char.isprintable()).strip()
        match = re.search(r"(MatchStart|RoundStart|RoundTime|Timeout|Resume|RoundEnd|MatchEnd):\s*([^\r\n]*)", printable, re.I)
        if not match:
            return
        action, value = match.group(1).lower(), match.group(2)
        update = {"event": "state"}
        if action == "matchstart":
            number = re.search(r"\d+", value)
            if number: update["match_number"] = number.group()
            update.update(running=False, timeout_active=False)
        elif action == "roundstart":
            number = re.search(r"\d+", value)
            if number: update["round"] = max(1, min(3, int(number.group())))
            update.update(running=True, timeout_active=False)
        elif action == "roundtime":
            seconds = self._time_seconds(value)
            if seconds is not None: update["seconds"] = seconds
        elif action == "resume":
            update.update(running=True, timeout_active=False)
        elif action == "timeout":
            update.update(running=False, timeout_active=True)
        elif action in ("roundend", "matchend"):
            update.update(running=False, timeout_active=False)
        self.packet.emit(update)
        if action == "matchend":
            self.packet.emit({"event": "fight_finished"})
