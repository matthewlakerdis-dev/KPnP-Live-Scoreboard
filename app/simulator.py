"""Virtual KPNP equipment producing normalized packet-like events."""

import random
import time

from PySide6.QtCore import QObject, QTimer, Signal


class KPNPEquipmentSimulator(QObject):
    packet = Signal(dict)
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.connected = False
        self.automatic = False
        self.sequence = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._automatic_event)
        self.timer.setInterval(850)

    def connect_equipment(self):
        if self.connected:
            return
        self.connected = True
        self.status.emit("Virtual KPNP equipment connected")
        self._emit("connection", connected=True, device="KPNP-VIRTUAL-01")

    def disconnect_equipment(self):
        self.set_automatic(False)
        if not self.connected:
            return
        self._emit("connection", connected=False, device="KPNP-VIRTUAL-01")
        self.connected = False
        self.status.emit("Virtual KPNP equipment disconnected")

    def set_automatic(self, enabled):
        self.automatic = bool(enabled)
        if self.automatic:
            self.connect_equipment()
            self.timer.start()
            self.status.emit("Automatic virtual match running")
        else:
            self.timer.stop()
            if self.connected:
                self.status.emit("Virtual equipment connected — manual mode")

    def hit(self, side, strength):
        self.connect_equipment()
        self._emit("pss_hit", side=side, strength=max(0, min(100, int(strength))))

    def simultaneous_hit(self, strength):
        self.hit("blue", strength)
        self.hit("red", max(10, min(100, strength + random.randint(-12, 12))))

    def score(self, side, points=1):
        self.connect_equipment(); self._emit("score", side=side, delta=int(points))

    def gamjeom(self, side, delta=1):
        self.connect_equipment(); self._emit("gamjeom", side=side, delta=int(delta))

    def round_win(self, side):
        self.connect_equipment(); self._emit("round_win", side=side, delta=1)

    def clock(self, action):
        self.connect_equipment(); self._emit("clock", action=action)

    def next_round(self):
        self.connect_equipment(); self._emit("next_round")

    def _automatic_event(self):
        if not self.connected:
            return
        side = random.choice(("blue", "red"))
        roll = random.random()
        if roll < .58:
            strength = random.randint(25, 100)
            self.hit(side, strength)
            if strength >= 48 and random.random() < .62:
                QTimer.singleShot(180, lambda s=side: self.score(s, random.choice((1, 2, 2, 3))))
        elif roll < .72:
            self.simultaneous_hit(random.randint(35, 95))
        elif roll < .87:
            self.score(side, random.choice((1, 2, 3)))
        elif roll < .96:
            self.gamjeom(side)
        else:
            self.round_win(side)

    def _emit(self, event, **payload):
        self.sequence += 1
        self.packet.emit({"source": "KPNP-VIRTUAL", "sequence": self.sequence,
                          "timestamp": round(time.time(), 3), "event": event, **payload})
