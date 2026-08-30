from __future__ import annotations

import math
import os
import random
import sys
import json
import ctypes
from dataclasses import dataclass
from pathlib import Path

# PyInstaller/Qt on Windows can otherwise resolve native dependencies relative
# to the caller's working folder. Normalize it before importing any Qt module.
if getattr(sys, "frozen", False):
    os.chdir(Path(sys.executable).resolve().parent)
if sys.platform == "win32":
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("KPNP.LiveScoreboard.v3")

from PySide6.QtCore import QDir, QObject, QPointF, QRectF, QSettings, QStandardPaths, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontDatabase, QFontMetricsF, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QTextEdit, QToolButton, QVBoxLayout, QWidget, QMessageBox, QProgressBar)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
import pycountry
from kpnp_listener import KPNPListener
from daedo_listener import DaedoListener
from simulator import KPNPEquipmentSimulator
from updater import UpdateManager
from version import APP_VERSION


BASE_W, BASE_H = 1273, 261


def asset_path(*parts):
    executable_assets = Path(sys.executable).resolve().parent / "assets"
    if executable_assets.exists():
        return executable_assets.joinpath(*parts)
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root.joinpath("assets", *parts)


def fit_combo_to_items(combo):
    """Use only the width needed by the longest choice plus its arrow."""
    text_width=max((combo.fontMetrics().horizontalAdvance(combo.itemText(i)) for i in range(combo.count())),default=0)
    combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
    combo.setFixedWidth(text_width+66)


class WheelSafeComboBox(QComboBox):
    """Keep dashboard scrolling from changing a selection by accident."""

    def wheelEvent(self,event):
        event.ignore()


class WheelSafeSpinBox(QSpinBox):
    """Let the mouse wheel scroll the dashboard, never alter a number."""

    def wheelEvent(self,event):
        event.ignore()


@dataclass
class Side:
    country: str
    nation: str
    first: str
    last: str
    alpha2: str = ""
    score: int = 0
    rounds: int = 0
    gamjeom: int = 0
    pss: float = 0.0
    peak: float = 0.0
    portrait: str = ""


class MatchState(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.blue = Side("AUS", "AUSTRALIA", "CHONG", "", "AU")
        self.red = Side("AUS", "AUSTRALIA", "HONG", "", "AU")
        self.match_number = 101
        self.round = 1
        self.seconds = 90
        self.running = False
        self.timeout_active = False
        self._hold = {"blue": 0, "red": 0}
        for key in ("blue", "red"):
            default = asset_path("portraits", f"{key}.png")
            if default.exists(): getattr(self, key).portrait = str(default)

    def update(self, **values):
        for key, value in values.items():
            if key.startswith("blue_") or key.startswith("red_"):
                side_name, field = key.split("_", 1)
                if hasattr(getattr(self, side_name), field): setattr(getattr(self, side_name), field, value)
            elif hasattr(self, key): setattr(self, key, value)
        self.changed.emit()

    def impact(self, side, strength):
        player = getattr(self, side)
        player.pss = max(player.pss, float(strength))
        player.peak = max(player.peak, player.pss)
        self._hold[side] = 9
        self.changed.emit()

    def tick(self):
        dirty = False
        for key in ("blue", "red"):
            player = getattr(self, key)
            if self._hold[key]: self._hold[key] -= 1
            elif player.pss > 0:
                player.pss = max(0, player.pss - max(1.5, player.pss * .075)); dirty = True
            if player.peak > player.pss and not self._hold[key]:
                player.peak = max(player.pss, player.peak - 1.0); dirty = True
        if dirty: self.changed.emit()

    def reset_defaults(self):
        defaults = {
            "blue": Side("AUS", "AUSTRALIA", "CHONG", "", "AU"),
            "red": Side("AUS", "AUSTRALIA", "HONG", "", "AU"),
        }
        for side_name, default in defaults.items():
            side = getattr(self, side_name)
            for field in Side.__dataclass_fields__:
                setattr(side, field, getattr(default, field))
            portrait = asset_path("portraits", f"{side_name}.png")
            if portrait.exists(): side.portrait = str(portrait)
        self.match_number = 101
        self.round = 1
        self.seconds = 90
        self.running = False
        self.timeout_active = False
        self._hold = {"blue": 0, "red": 0}
        self.changed.emit()


class FlagStore(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent); self.network=QNetworkAccessManager(self); self.pending=set()
        self.folder=Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))/"flags"
        QDir().mkpath(str(self.folder))
        kpnp_folder=asset_path("kpnp_flags")
        self.kpnp_flags={path.stem.casefold():path for path in kpnp_folder.glob("*") if path.is_file()}

    def image(self, alpha2, nation=""):
        kpnp_path=self.kpnp_flags.get((nation or "").casefold())
        if kpnp_path:
            image=QImage(str(kpnp_path))
            if not image.isNull(): return image
        code=(alpha2 or "").lower(); bundled=asset_path("flags",f"{code}.png")
        image=QImage(str(bundled))
        if not image.isNull(): return image
        path=self.folder/f"{code}.png"
        image=QImage(str(path))
        if not image.isNull(): return image
        if len(code)==2 and code not in self.pending:
            self.pending.add(code); reply=self.network.get(QNetworkRequest(QUrl(f"https://flagcdn.com/w160/{code}.png")))
            reply.finished.connect(lambda r=reply,c=code,p=path:self._finished(r,c,p))
        return QImage()

    def _finished(self, reply, code, path):
        self.pending.discard(code)
        if reply.error()==QNetworkReply.NoError:
            image=QImage.fromData(bytes(reply.readAll()))
            if not image.isNull(): image.save(str(path),"PNG"); self.changed.emit()
        reply.deleteLater()


class Scoreboard(QWidget):
    def __init__(self, state):
        super().__init__(); self.state = state; state.changed.connect(self.update); self.flags=FlagStore(self); self.flags.changed.connect(self.update)
        self.design = "Original"
        self.setWindowTitle("KPNP Broadcast Output v3")
        self.setWindowIcon(QIcon(str(asset_path("app.ico"))))
        self.borderless = False
        self.setAttribute(Qt.WA_TranslucentBackground,True); self.setAutoFillBackground(False)
        self.setMinimumSize(900, 182); self.resize(BASE_W, BASE_H)
        self.setStyleSheet("background:transparent")

    def toggle_borderless(self):
        geometry=self.geometry(); self.borderless=not self.borderless
        self.setWindowFlag(Qt.FramelessWindowHint,self.borderless)
        self.show(); self.setGeometry(geometry); self.raise_()

    def set_design(self, design):
        self.design = design
        self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        scale = min(self.width()/BASE_W, self.height()/BASE_H)
        ox, oy = (self.width()-BASE_W*scale)/2, (self.height()-BASE_H*scale)/2
        p.translate(ox, oy); p.scale(scale, scale)
        if self.design == "Modern":
            self.draw_alternative(p, False)
        elif self.design == "Arena":
            self.draw_alternative(p, True)
        elif self.design == "Flat Strip":
            self.draw_simple(p,"flat")
        elif self.design == "Rounded Cards":
            self.draw_simple(p,"cards")
        elif self.design == "Minimal Broadcast":
            self.draw_simple(p,"minimal")
        elif self.design == "Wing Compact":
            self.draw_wing_compact(p)
        else:
            self.draw_background(p)
            self.draw_side(p, self.state.blue, True)
            self.draw_side(p, self.state.red, False)
            self.draw_center(p)

    def font(self, size, weight=QFont.Bold, condensed=True):
        f = QFont("Segoe UI", size, weight); f.setStretch(QFont.Condensed if condensed else QFont.Unstretched); f.setLetterSpacing(QFont.PercentageSpacing, 96); return f

    def text(self, p, rect, text, size, color="white", align=Qt.AlignCenter, weight=QFont.Bold):
        p.setFont(self.font(size, weight)); p.setPen(QColor(color)); p.drawText(QRectF(*rect), align, str(text))

    def fit_text(self,p,rect,text,max_size,min_size=9,color="white",align=Qt.AlignCenter,weight=QFont.Bold,padding=4):
        target=QRectF(*rect).adjusted(padding,2,-padding,-2); value=str(text)
        size=max_size
        while size>min_size:
            font=self.font(size,weight); metrics=QFontMetricsF(font)
            if metrics.horizontalAdvance(value)<=target.width() and metrics.height()<=target.height(): break
            size-=1
        p.setFont(self.font(size,weight)); p.setPen(QColor(color)); p.drawText(target,align,value)

    def panel(self, p, points, top, bottom, edge):
        path = QPainterPath(); path.addPolygon(QPolygonF([QPointF(*x) for x in points])); path.closeSubpath()
        g = QLinearGradient(0, min(y for _,y in points), 0, max(y for _,y in points)); g.setColorAt(0,QColor(top)); g.setColorAt(1,QColor(bottom))
        p.save(); p.setBrush(QBrush(g)); p.setPen(QPen(QColor(edge),2)); p.drawPath(path); p.setPen(QPen(QColor(255,255,255,70),1)); p.drawPolyline(QPolygonF([QPointF(x,y+4) for x,y in points[:4]])); p.restore()

    def draw_background(self,p):
        p.save(); p.setCompositionMode(QPainter.CompositionMode_Source); p.fillRect(QRectF(0,0,BASE_W,BASE_H),QColor(0,0,0,0)); p.restore(); p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        self.panel(p,[(20,27),(40,21),(482,21),(567,198),(530,237),(20,237)],"#061a3c","#001126","#078cff")
        self.panel(p,[(1253,27),(1233,21),(791,21),(706,198),(743,237),(1253,237)],"#3d0507","#180002","#ff2828")
        # fine inner broadcast rails
        p.setPen(QPen(QColor("#0f5eb7"),1)); p.drawPolyline(QPolygonF([QPointF(27,31),QPointF(43,26),QPointF(475,26),QPointF(558,198),QPointF(524,232),QPointF(25,232),QPointF(25,31)]))
        p.setPen(QPen(QColor("#a71419"),1)); p.drawPolyline(QPolygonF([QPointF(1246,31),QPointF(1230,26),QPointF(798,26),QPointF(715,198),QPointF(749,232),QPointF(1248,232),QPointF(1248,31)]))

    def portrait(self,p,rect,path,blue):
        x,y,w,h=rect; clip=QPainterPath(); clip.addRoundedRect(QRectF(x,y,w,h),8,8); p.save(); p.setClipPath(clip)
        if path and QImage(path).isNull() is False:
            img=QImage(path); scaled=img.scaled(int(w),int(h),Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation); p.drawImage(QRectF(x,y,w,h),scaled,QRectF((scaled.width()-w)/2,0,w,h))
        else:
            g=QLinearGradient(x,y,x+w,y+h); g.setColorAt(0,QColor("#092e67" if blue else "#681111")); g.setColorAt(1,QColor("#05090e")); p.fillRect(QRectF(x,y,w,h),g)
            p.setBrush(QColor(215,220,225)); p.setPen(Qt.NoPen); p.drawEllipse(QRectF(x+w*.34,y+18,w*.32,w*.32)); p.drawRoundedRect(QRectF(x+w*.20,y+h*.44,w*.60,h*.55),25,18)
            p.setBrush(QColor("#0865d8" if blue else "#db1717")); p.drawRoundedRect(QRectF(x+w*.12,y+h*.60,w*.76,h*.40),18,12)
            self.text(p,(x,y+h-29,w,20),"KPNP",12,"white")
        p.restore()

    def flag(self,p,x,y,code,alpha2="",nation=""):
        image=self.flags.image(alpha2,nation)
        if not image.isNull():
            p.setPen(QPen(QColor("#aab2ba"),1)); p.setBrush(QColor("#f3f3f3")); p.drawRect(QRectF(x,y,71,47)); p.drawImage(QRectF(x+1,y+1,69,45),image); return
        p.setBrush(QColor("#f3f3f3")); p.setPen(QPen(QColor("#9aa3ad"),1)); p.drawRect(QRectF(x,y,71,47))
        if code.upper()=="KOR":
            p.setBrush(QColor("#d71d30")); p.setPen(Qt.NoPen); p.drawPie(QRectF(x+25,y+10,22,22),0,180*16); p.setBrush(QColor("#174b9a")); p.drawPie(QRectF(x+25,y+10,22,22),180*16,180*16)
        elif code.upper()=="AUS":
            p.fillRect(QRectF(x,y,71,47),QColor("#08194b")); p.setPen(QPen(Qt.white,3)); p.drawLine(x,y,x+31,y+21); p.drawLine(x+31,y,x,y+21); p.setPen(QPen(QColor("#e32b3d"),2)); p.drawLine(x,y,x+31,y+21); p.drawLine(x+31,y,x,y+21); p.setBrush(Qt.white); p.setPen(Qt.NoPen); p.drawEllipse(QRectF(x+51,y+27,5,5))
        else: self.text(p,(x,y,71,47),code[:3],14,"#1b2530")

    def draw_side(self,p,s,left):
        blue=left; accent="#168cff" if blue else "#f6242d"
        if left:
            self.flag(p,39,40,s.country,s.alpha2,s.nation)
            self.panel(p,[(119,29),(477,29),(533,80),(510,99),(151,99)],"#0a65e0","#06336f","#147cff")
            self.fit_text(p,(139,35,366,57),f"{s.first} {s.last}".strip(),24,12,"white",Qt.AlignLeft|Qt.AlignVCenter)
            score_rect=(316,99,194,134); score_align=Qt.AlignCenter
            label_rects=[(44,105,124,42),(44,147,124,42),(44,189,124,42)]
            # Mirror the red layout: blue rows finish on one shared guide.
            lamp_starts=[222,177,173]
        else:
            self.flag(p,1163,40,s.country,s.alpha2,s.nation)
            self.panel(p,[(1154,29),(796,29),(740,80),(763,99),(1122,99)],"#d30c12","#6f0709","#f6242d")
            self.fit_text(p,(768,35,366,57),f"{s.first} {s.last}".strip(),24,12,"white",Qt.AlignRight|Qt.AlignVCenter)
            score_rect=(763,99,194,134); score_align=Qt.AlignCenter
            label_rects=[(1104,105,124,42),(1104,147,124,42),(1104,189,124,42)]
            # Align the red indicators from the left, leaving the label column clear.
            lamp_starts=[970,970,970]
        score_text=str(s.score); score_size=88 if len(score_text)<3 else 66
        p.save(); score_font=self.font(score_size,QFont.Bold); score_font.setLetterSpacing(QFont.PercentageSpacing,108); p.setFont(score_font); p.setPen(QColor("white")); p.drawText(QRectF(*score_rect),score_align,score_text); p.restore()
        # three dark glass status rails
        for y in (105,147,189):
            if left: poly=[(25,y),(316,y),(339,y+42),(25,y+42)]
            else: poly=[(1248,y),(957,y),(934,y+42),(1248,y+42)]
            path=QPainterPath(); path.addPolygon(QPolygonF([QPointF(*pt) for pt in poly])); path.closeSubpath(); rail=QColor(accent); rail.setAlpha(100); p.save(); p.setBrush(QBrush(QColor(1,8,17,235))); p.setPen(QPen(rail,1)); p.drawPath(path); p.restore()
        labels=("ROUNDS","GAM-JEOM","PSS")
        for i,label in enumerate(labels):
            align=(Qt.AlignLeft if left else Qt.AlignRight)|Qt.AlignVCenter; self.text(p,label_rects[i],label,14,"#e8e8e8",align,QFont.Bold)
        # exactly three round lamps
        for i in range(3):
            x=lamp_starts[0]+i*31; active=(i<s.rounds) if left else (i>=3-s.rounds); fill=accent if active else "#070a0d"
            p.setBrush(QColor(fill)); p.setPen(QPen(QColor("white" if not active else accent),1)); p.drawEllipse(QRectF(x,117,19,19))
        # exactly five yellow Gam-jeom lamps
        for i in range(5):
            x=lamp_starts[1]+i*27; active=(i<s.gamjeom) if left else (i>=5-s.gamjeom); p.setBrush(QColor("#ffd000" if active else "#070a0d")); p.setPen(QPen(QColor("#ffd000" if active else "#767d83"),1)); p.drawEllipse(QRectF(x,159,18,18))
        # segmented rising PSS meter; attack/hold/decay are driven by MatchState
        # Keep the meter inside the straight portion of the beveled status rail;
        # it must not run beneath the diagonal score-panel join.
        power_x, power_width = ((90,213) if left else (970,213))
        self.power(p,power_x,202,power_width,s.pss,s.peak,reverse=not left)

    def power(self,p,x,y,w,value,peak,reverse=False):
        # Preserve the original slim segment proportions as the meter grows.
        # Wider designs receive more segments instead of wider blocks.
        gap=1.5
        bars=max(28,round((w+gap)/7.0))
        bw=(w-gap*(bars-1))/bars
        for i in range(bars):
            h=20; level=(i+1)*(100/bars); active=value>=level-(50/bars)
            # Colour zones are percentage based so they remain consistent when
            # wider designs add extra segments. Red is reserved for 90-100%.
            ratio=(i+1)/bars
            c=QColor("#30f51c" if ratio<=.75 else "#f5d51c" if ratio<=.90 else "#ff3824")
            if not active: c=QColor(25,45,42)
            position=bars-1-i if reverse else i
            p.fillRect(QRectF(x+position*(bw+gap),y+18-h,bw,h),c)

    def draw_center(self,p):
        self.panel(p,[(581,27),(692,27),(724,49),(704,70),(569,70),(549,49)],"#16191c","#030405","#666c70")
        self.fit_text(p,(575,27,124,42),self.state.match_number,30,12,"white")
        sec=max(0,self.state.seconds); minute_digits=str(sec//60); second_digits=f"{sec%60:02d}"
        self.panel(p,[(541,74),(732,74),(746,87),(746,150),(731,163),(542,163),(527,150),(527,87)],"#15191d","#030405","#8b9298")
        # Convert the complete timer to a vector path. Unlike drawText(rect), a
        # path has no glyph box that can crop wide numeral overhangs.
        clock=f"{minute_digits} : {second_digits[0]} {second_digits[1]}"; point_size=52
        while True:
            timer_font=QFont("Segoe UI",point_size,QFont.Bold); timer_font.setStretch(QFont.Condensed)
            timer_path=QPainterPath(); timer_path.addText(0,0,timer_font,clock); timer_bounds=timer_path.boundingRect()
            if (timer_bounds.width()<=164 and timer_bounds.height()<=64) or point_size<=14: break
            point_size-=1
        if self.state.timeout_active: self.text(p,(566,78,141,18),"TIME OUT",12,"#ffd000")
        timer_center_y=125 if self.state.timeout_active else 117.5
        p.save(); p.translate(636.5-timer_bounds.center().x(),timer_center_y-timer_bounds.center().y()); p.fillPath(timer_path,QColor("white" if self.state.running else "#ffd000")); p.restore()
        tab=QPolygonF([QPointF(548,163),QPointF(725,163),QPointF(703,193),QPointF(570,193)])
        g=QLinearGradient(0,163,0,193); g.setColorAt(0,QColor("#ffe400")); g.setColorAt(1,QColor("#ffb900")); p.save(); p.setBrush(QBrush(g)); p.setPen(Qt.NoPen); p.drawPolygon(tab); p.restore(); self.text(p,(571,163,132,27),"MATCH TIME",14,"#050505")
        self.panel(p,[(566,195),(707,195),(724,217),(707,238),(566,238),(549,217)],"#121518","#030405","#6e7376")
        self.text(p,(593,196,86,18),"ROUNDS",11,"#efefef")
        for i,x in enumerate((599,628,657)):
            active=i<=self.state.round-1
            p.setBrush(QColor("#ffd000" if active else "#303538")); p.setPen(QPen(QColor("#ffe56b" if active else "#8b9297"),1)); p.drawEllipse(QRectF(x-2,216,20,20))

    def draw_alternative(self,p,arena=False):
        p.save(); p.setCompositionMode(QPainter.CompositionMode_Source); p.fillRect(QRectF(0,0,BASE_W,BASE_H),QColor(0,0,0,0)); p.restore(); p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        gold="#ffc62b"; blue="#086cf0"; red="#e51c25"
        if arena:
            self.panel(p,[(18,39),(48,23),(520,23),(555,57),(537,238),(45,238),(18,218)],"#073a91","#020b1c",blue)
            self.panel(p,[(1255,39),(1225,23),(753,23),(718,57),(736,238),(1228,238),(1255,218)],"#8e090d","#1b0204",red)
            self.panel(p,[(526,22),(747,22),(730,239),(543,239)],"#202020","#030303",gold)
        else:
            self.panel(p,[(20,35),(535,35),(556,61),(535,234),(20,234)],"#071b37","#020914",blue)
            self.panel(p,[(1253,35),(738,35),(717,61),(738,234),(1253,234)],"#351014","#110407",red)
            self.panel(p,[(536,35),(737,35),(754,58),(725,234),(548,234),(519,58)],"#17191d","#050607","#5b6168")
        self.draw_alternative_side(p,self.state.blue,True,arena)
        self.draw_alternative_side(p,self.state.red,False,arena)
        # Match number, timer and current round remain central in every design.
        self.fit_text(p,(575,28,124,40),self.state.match_number,30,12,"white")
        sec=max(0,self.state.seconds); clock=f"{sec//60}:{sec%60:02d}"
        if self.state.timeout_active: self.text(p,(566,69,141,20),"TIME OUT",12,gold)
        self.fit_text(p,(548,89,177,50) if self.state.timeout_active else (548,72,177,67),clock,48 if self.state.timeout_active else 52,24,gold if arena or not self.state.running else "white")
        self.text(p,(568,143,137,25),"MATCH TIME",14,gold if arena else "#d8dde3")
        self.text(p,(586,176,101,24),"ROUNDS",15,"white")
        for i,x in enumerate((601,629,657)):
            active=i<=self.state.round-1; p.setBrush(QColor(gold if active else "#20252a")); p.setPen(QPen(QColor(gold if active else "#767d83"),1)); p.drawEllipse(QRectF(x-2,204,21,21))

    def draw_alternative_side(self,p,s,left,arena):
        accent="#086cf0" if left else "#e51c25"; gold="#ffc62b"
        if left:
            self.flag(p,43,50,s.country,s.alpha2,s.nation); self.fit_text(p,(124,48,283,51),f"{s.first} {s.last}".strip(),24,11,"white",Qt.AlignLeft|Qt.AlignVCenter)
            self.fit_text(p,(420,37,102,72),s.score,62,30); label_x=48; round_x=195; gam_x=195; power_x=188; power_width=322
        else:
            self.flag(p,1159,50,s.country,s.alpha2,s.nation); self.fit_text(p,(866,48,279,51),f"{s.first} {s.last}".strip(),24,11,"white",Qt.AlignRight|Qt.AlignVCenter)
            self.fit_text(p,(751,37,102,72),s.score,62,30); label_x=1090; round_x=997; gam_x=952; power_x=763; power_width=317
        line="#35414d" if not arena else accent
        p.setPen(QPen(QColor(line),1)); p.drawLine(40 if left else 753,108,520 if left else 1233,108); p.drawLine(40 if left else 753,150,520 if left else 1233,150); p.drawLine(40 if left else 753,190,520 if left else 1233,190)
        align=(Qt.AlignLeft if left else Qt.AlignRight)|Qt.AlignVCenter
        self.text(p,(label_x,110,130,35),"ROUNDS",14,"#eef2f6",align); self.text(p,(label_x,151,130,35),"GAM-JEOM",14,"#eef2f6",align); self.text(p,(label_x,193,130,31),"PSS",14,"#eef2f6",align)
        for i in range(3):
            active=(i<s.rounds) if left else (i>=3-s.rounds); x=round_x+i*31; p.setBrush(QColor(accent if active else "#090c10")); p.setPen(QPen(QColor(accent if active else "#8a9198"),1)); p.drawEllipse(QRectF(x,117,19,19))
        for i in range(5):
            active=(i<s.gamjeom) if left else (i>=5-s.gamjeom); x=gam_x+i*27; p.setBrush(QColor(gold if active else "#090c10")); p.setPen(QPen(QColor(gold),1)); p.drawEllipse(QRectF(x,159,18,18))
        self.power(p,power_x,205,power_width,s.pss,s.peak,reverse=not left)

    def draw_simple(self,p,style):
        p.save(); p.setCompositionMode(QPainter.CompositionMode_Source); p.fillRect(QRectF(0,0,BASE_W,BASE_H),QColor(0,0,0,0)); p.restore(); p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        blue="#063b85"; red="#a80d16"; dark="#17191c"; gold="#ffd21f"
        if style=="cards":
            p.setPen(QPen(QColor("#2379ef"),2)); p.setBrush(QColor("#073e91")); p.drawRoundedRect(QRectF(18,22,496,217),16,16)
            p.setPen(QPen(QColor("#42464b"),2)); p.setBrush(QColor("#111315")); p.drawRoundedRect(QRectF(527,22,219,217),16,16)
            p.setPen(QPen(QColor("#ed3038"),2)); p.setBrush(QColor("#a80d16")); p.drawRoundedRect(QRectF(759,22,496,217),16,16)
            bounds=(18,514,527,746,759,1255)
        else:
            p.setPen(Qt.NoPen); p.setBrush(QColor(dark)); p.drawRect(QRectF(18,35,1237,191))
            if style=="flat":
                p.setBrush(QColor(blue)); p.drawRect(QRectF(18,35,515,191)); p.setBrush(QColor(red)); p.drawRect(QRectF(740,35,515,191))
            else:
                p.setBrush(QColor("#0878ff")); p.drawRect(QRectF(18,35,5,191)); p.setBrush(QColor("#ff2832")); p.drawRect(QRectF(1250,35,5,191))
            p.setPen(QPen(QColor("#62666b"),1)); p.drawLine(533,45,533,216); p.drawLine(740,45,740,216)
            bounds=(18,533,533,740,740,1255)
        self.draw_simple_side(p,self.state.blue,True,style,bounds[0],bounds[1])
        self.draw_simple_side(p,self.state.red,False,style,bounds[4],bounds[5])
        cx0,cx1=bounds[2],bounds[3]; cw=cx1-cx0
        sec=max(0,self.state.seconds); timer=f"{sec//60}:{sec%60:02d}"
        self.fit_text(p,(cx0,35,cw,35),self.state.match_number,30,11,"white")
        if self.state.timeout_active: self.text(p,(cx0,68,cw,18),"TIME OUT",12,gold)
        self.fit_text(p,(cx0,86,cw,43) if self.state.timeout_active else (cx0,70,cw,58),timer,40 if self.state.timeout_active else 47,24,gold if not self.state.running else "white")
        self.text(p,(cx0,131,cw,22),"MATCH TIME",13,gold)
        self.text(p,(cx0,161,cw,24),"ROUNDS",15,"white")
        start=cx0+cw/2-41
        for i in range(3):
            active=i<=self.state.round-1; p.setBrush(QColor(gold if active else "#4b4f53")); p.setPen(Qt.NoPen); p.drawEllipse(QRectF(start-2+i*31,192,22,22))

    def draw_simple_side(self,p,s,left,style,x0,x1):
        width=x1-x0; accent="#168cff" if left else "#f22b34"; gold="#ffd21f"
        if left:
            self.flag(p,x0+25,51,s.country,s.alpha2,s.nation); self.fit_text(p,(x0+108,50,width-230,48),f"{s.first} {s.last}".strip(),22,10,"white",Qt.AlignLeft|Qt.AlignVCenter); self.fit_text(p,(x1-105,43,88,61),s.score,52,28)
        else:
            self.fit_text(p,(x0+17,43,88,61),s.score,52,28); self.fit_text(p,(x0+116,50,width-224,48),f"{s.first} {s.last}".strip(),22,10,"white",Qt.AlignRight|Qt.AlignVCenter); self.flag(p,x1-96,51,s.country,s.alpha2,s.nation)
        yline=108 if style!="cards" else 111; p.setPen(QPen(QColor(255,255,255,75),1)); p.drawLine(x0+20,yline,x1-20,yline)
        if style=="minimal":
            label_y=123; self.text(p,(x0+26,label_y,76,25),"ROUNDS",12,"#e8e8e8",Qt.AlignLeft|Qt.AlignVCenter); self.text(p,(x0+235,label_y,91,25),"GAM-JEOM",12,"#e8e8e8",Qt.AlignLeft|Qt.AlignVCenter)
            round_x=x0+112; gam_x=x0+332; lamp_y=127
            for i in range(3):
                active=(i<s.rounds) if left else (i>=3-s.rounds); p.setBrush(QColor(accent if active else "#171a1d")); p.setPen(QPen(QColor(accent if active else "#858b91"),1)); p.drawEllipse(QRectF(round_x+i*31,lamp_y,17,17))
            for i in range(5):
                active=(i<s.gamjeom) if left else (i>=5-s.gamjeom); p.setBrush(QColor(gold if active else "#171a1d")); p.setPen(QPen(QColor(gold),1)); p.drawEllipse(QRectF(gam_x+i*29,lamp_y,16,16))
            if left:
                self.text(p,(x0+26,166,55,25),"PSS",13,"#e8e8e8",Qt.AlignLeft|Qt.AlignVCenter)
                self.power(p,x0+91,170,max(80,width-116),s.pss,s.peak)
            else:
                self.text(p,(x1-81,166,55,25),"PSS",13,"#e8e8e8",Qt.AlignRight|Qt.AlignVCenter)
                self.power(p,x0+25,170,max(80,width-116),s.pss,s.peak,True)
        else:
            label_y=116; self.text(p,(x0+35,label_y,150,25),"ROUNDS",12,"white"); self.text(p,(x0+230,label_y,180,25),"GAM-JEOM",12,"white")
            for i in range(3):
                active=(i<s.rounds) if left else (i>=3-s.rounds); p.setBrush(QColor(accent if active else "#202429")); p.setPen(QPen(QColor("#a4a9ae"),1)); p.drawEllipse(QRectF(x0+70+i*31,151,18,18))
            for i in range(5):
                active=(i<s.gamjeom) if left else (i>=5-s.gamjeom); p.setBrush(QColor(gold if active else "#202429")); p.setPen(QPen(QColor(gold if active else "#a4a9ae"),1)); p.drawEllipse(QRectF(x0+254+i*29,151,17,17))
            if left:
                self.text(p,(x0+27,181,55,25),"PSS",13,"white",Qt.AlignLeft|Qt.AlignVCenter)
                self.power(p,x0+92,185,max(80,width-117),s.pss,s.peak)
            else:
                self.text(p,(x1-82,181,55,25),"PSS",13,"white",Qt.AlignRight|Qt.AlignVCenter)
                self.power(p,x0+25,185,max(80,width-117),s.pss,s.peak,True)

    def draw_wing_compact(self,p):
        p.save(); p.setCompositionMode(QPainter.CompositionMode_Source); p.fillRect(QRectF(0,0,BASE_W,BASE_H),QColor(0,0,0,0)); p.restore(); p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        blue="#0878ff"; red="#f12631"; gold="#ffd21f"
        self.panel(p,[(22,101),(47,79),(539,79),(563,96),(563,165),(539,181),(48,174),(22,153)],"#083c89","#03162f",blue)
        self.panel(p,[(1251,101),(1226,79),(734,79),(710,96),(710,165),(734,181),(1225,174),(1251,153)],"#8d0b12","#320407",red)
        # Main wing contents follow the score-name-flag / flag-name-score order from the sketch.
        self.fit_text(p,(55,94,98,68),self.state.blue.score,52,28)
        self.fit_text(p,(164,98,274,60),f"{self.state.blue.first} {self.state.blue.last}".strip(),25,10)
        self.flag(p,466,96,self.state.blue.country,self.state.blue.alpha2,self.state.blue.nation)
        self.flag(p,736,96,self.state.red.country,self.state.red.alpha2,self.state.red.nation)
        self.fit_text(p,(821,98,274,60),f"{self.state.red.first} {self.state.red.last}".strip(),25,10)
        self.fit_text(p,(1110,94,98,68),self.state.red.score,52,28)
        # Five Gam-jeom lamps at the outer top edges.
        for i in range(5):
            active=i<self.state.blue.gamjeom; p.setBrush(QColor(gold if active else "#090c10")); p.setPen(QPen(QColor(gold if active else "#9ca2a8"),1)); p.drawEllipse(QRectF(43+i*27,45,17,17))
            active=i>=5-self.state.red.gamjeom; x=1095+i*27; p.setBrush(QColor(gold if active else "#090c10")); p.setPen(QPen(QColor(gold if active else "#9ca2a8"),1)); p.drawEllipse(QRectF(x,45,17,17))
        # PSS meters appear only while a detected impact is active/decaying.
        if self.state.blue.pss>0: self.power(p,190,45,345,self.state.blue.pss,self.state.blue.peak)
        if self.state.red.pss>0: self.power(p,738,45,345,self.state.red.pss,self.state.red.peak,True)
        # Per-athlete rounds won form bottom-up vertical stacks beside each score.
        for i in range(3):
            active=i>=3-self.state.blue.rounds; p.setBrush(QColor(blue if active else "#15191d")); p.setPen(QPen(QColor(blue if active else "#8d949a"),1)); p.drawEllipse(QRectF(31,101+i*21,14,14))
            active=i>=3-self.state.red.rounds; p.setBrush(QColor(red if active else "#15191d")); p.setPen(QPen(QColor(red if active else "#8d949a"),1)); p.drawEllipse(QRectF(1228,101+i*21,14,14))
        # Central match number, timer and current-round indicators.
        p.setBrush(QColor("#0a0c0f")); p.setPen(QPen(QColor("#777d82"),2)); p.drawRoundedRect(QRectF(548,68,177,116),16,16)
        p.setBrush(QColor("#0a0c0f")); p.setPen(QPen(QColor("#777d82"),2)); p.drawRoundedRect(QRectF(586,23,101,40),10,10)
        self.fit_text(p,(589,24,95,38),self.state.match_number,30,11,"white")
        if self.state.timeout_active: self.text(p,(566,73,141,21),"TIME OUT",13,gold)
        sec=max(0,self.state.seconds); second_digits=f"{sec%60:02d}"; timer_rect=(548,98,177,64) if self.state.timeout_active else (548,91,177,67); self.fit_text(p,timer_rect,f"{sec//60} : {second_digits}",42,24,gold if not self.state.running else "white")
        self.text(p,(568,180,137,24),"ROUNDS",14,"#d5d9dd")
        for i,x in enumerate((601,629,657)):
            active=i<=self.state.round-1; p.setBrush(QColor(gold if active else "#33383d")); p.setPen(QPen(QColor(gold if active else "#8d949a"),1)); p.drawEllipse(QRectF(x-2,207,21,21))


class CollapsibleSection(QWidget):
    def __init__(self,title,parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Maximum)
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0); layout.setSpacing(4)
        self.toggle=QToolButton(text=title,checkable=True,checked=True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon); self.toggle.setArrowType(Qt.DownArrow)
        self.toggle.setObjectName("sectionToggle")
        self.content=QWidget(); self.content_layout=QVBoxLayout(self.content); self.content_layout.setContentsMargins(0,0,0,0)
        self.toggle.toggled.connect(self.set_expanded)
        layout.addWidget(self.toggle); layout.addWidget(self.content)

    def set_expanded(self,expanded):
        self.toggle.blockSignals(True); self.toggle.setChecked(expanded); self.toggle.blockSignals(False)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.content.setVisible(expanded)


class Operator(QMainWindow):
    def __init__(self,state,board):
        super().__init__(); self.state=state; self.board=board; self.setWindowTitle(f"KPNP Scoreboard v{APP_VERSION} — Operator"); self.resize(640,860); self.setMinimumWidth(600)
        self.setObjectName("operatorWindow")
        self.setWindowIcon(QIcon(str(asset_path("app.ico"))))
        self.kpnp_listener=KPNPListener(self); self.daedo_listener=DaedoListener(self); self.listener=self.kpnp_listener
        for listener in (self.kpnp_listener,self.daedo_listener):
            listener.packet.connect(self.apply_packet); listener.status.connect(self.listener_status)
        self.simulator=KPNPEquipmentSimulator(self); self.simulator.packet.connect(self.route_simulator_packet)
        self.settings=QSettings("KPNP Scoreboard","Live Scoreboard v3")
        self.updater=UpdateManager(self)
        self.dashboard_scroll=QScrollArea(); self.dashboard_scroll.setObjectName("dashboardScroll"); self.dashboard_scroll.setWidgetResizable(True); self.dashboard_scroll.setFrameShape(QFrame.NoFrame); self.dashboard_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.setCentralWidget(self.dashboard_scroll)
        root=QWidget(); root.setObjectName("dashboardPage"); self.dashboard_scroll.setWidget(root); outer=QVBoxLayout(root); outer.setContentsMargins(12,12,12,14); outer.setSpacing(8)
        outer.addWidget(self.connection_group())
        outer.addWidget(self.update_group())
        output_card=QGroupBox("Output"); output_card.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Maximum); output_outer=QHBoxLayout(output_card); output_outer.addStretch(1)
        top=QGridLayout(); top.setHorizontalSpacing(14); top.setVerticalSpacing(12); output_outer.addLayout(top); output_outer.addStretch(1)
        self.show_output_button=QPushButton("Show output"); self.show_output_button.setObjectName("primaryButton"); self.show_output_button.clicked.connect(self.toggle_output)
        borderless=QPushButton("Toggle borderless"); borderless.clicked.connect(self.toggle_borderless_output)
        self.design=WheelSafeComboBox(); self.design.addItems(("Original","Modern","Arena","Flat Strip","Rounded Cards","Minimal Broadcast","Wing Compact")); self.design.currentTextChanged.connect(self.design_changed)
        self.screen=WheelSafeComboBox(); self.screen.addItems([s.name() for s in QApplication.screens()]); move=QPushButton("Move output"); move.clicked.connect(self.move_output)
        for combo in (self.screen,self.design): fit_combo_to_items(combo)
        top.addWidget(self.show_output_button,0,0); top.addWidget(QLabel("Output screen"),0,1); top.addWidget(self.screen,0,2); top.addWidget(move,0,3)
        top.addWidget(borderless,1,0); top.addWidget(QLabel("Design"),1,1); top.addWidget(self.design,1,2)
        outer.addWidget(output_card)
        self.manual_data_groups=[]
        self.manual_section=CollapsibleSection("Scoreboard controls"); outer.addWidget(self.manual_section)
        self.manual_section.toggle.toggled.connect(lambda _:self.save_settings())
        sides=QVBoxLayout(); sides.setSpacing(8); sides.addWidget(self.side_group("Blue",state.blue)); sides.addWidget(self.side_group("Red",state.red)); self.manual_section.content_layout.addLayout(sides)
        match=QGroupBox("Match"); grid=QVBoxLayout(match); grid.setSpacing(7)
        self.match_number=WheelSafeSpinBox(); self.match_number.setRange(1,9999); self.match_number.setValue(state.match_number); self.match_number.valueChanged.connect(lambda v:state.update(match_number=v))
        self.round=WheelSafeSpinBox(); self.round.setRange(1,3); self.round.setValue(state.round); self.round.valueChanged.connect(lambda v:state.update(round=v))
        self.minutes=WheelSafeSpinBox(); self.minutes.setRange(0,99); self.minutes.setValue(state.seconds//60); self.seconds=WheelSafeSpinBox(); self.seconds.setRange(0,59); self.seconds.setValue(state.seconds%60)
        self.match_number.setFixedWidth(90); self.round.setFixedWidth(72); self.minutes.setFixedWidth(72); self.seconds.setFixedWidth(72)
        self.minutes.valueChanged.connect(self.set_clock); self.seconds.valueChanged.connect(self.set_clock)
        self.start=QPushButton("Start clock"); self.start.setCheckable(True); self.start.toggled.connect(self.clock_toggle)
        reset=QPushButton("Reset 1:30"); reset.clicked.connect(self.reset_clock)
        match_row=QHBoxLayout(); match_row.setContentsMargins(8,0,8,0); match_row.setSpacing(6); match_row.addStretch(1)
        match_row.addWidget(QLabel("Match number")); match_row.addWidget(self.match_number); match_row.addSpacing(8)
        match_row.addWidget(QLabel("Round")); match_row.addWidget(self.round); match_row.addSpacing(8)
        match_row.addWidget(QLabel("Time"))
        time_row=QHBoxLayout(); time_row.setContentsMargins(0,0,0,0); time_row.setSpacing(3)
        time_row.addWidget(self.minutes); time_row.addWidget(QLabel(":")); time_row.addWidget(self.seconds)
        match_row.addLayout(time_row); match_row.addStretch(1)
        button_row=QHBoxLayout(); button_row.setSpacing(7); button_row.addWidget(self.start,1); button_row.addWidget(reset,1)
        grid.addLayout(match_row); grid.addLayout(button_row); self.manual_section.content_layout.addWidget(match)
        self.manual_data_groups.append(match)
        self.sim_box=self.simulator_group(); outer.addWidget(self.sim_box)
        log_header=QHBoxLayout(); log_header.addWidget(QLabel("Listener output")); log_header.addStretch()
        clear_log=QPushButton("Clear"); clear_log.clicked.connect(lambda:self.event_log.clear())
        copy_log=QPushButton("Copy all"); copy_log.clicked.connect(self.copy_event_log)
        log_header.addWidget(clear_log); log_header.addWidget(copy_log); outer.addLayout(log_header)
        self.event_log=QTextEdit(); self.event_log.setReadOnly(True); self.event_log.setMaximumHeight(145); self.event_log.setPlaceholderText("Virtual and real KPNP events appear here…"); outer.addWidget(self.event_log)
        self.clock_timer=QTimer(self); self.clock_timer.timeout.connect(self.clock_step); self.clock_timer.start(1000)
        self.anim=QTimer(self); self.anim.timeout.connect(self.anim_step); self.anim.start(33)
        self.output_ui_timer=QTimer(self); self.output_ui_timer.timeout.connect(self.sync_output_button); self.output_ui_timer.start(500)
        self.restore_settings()
        QTimer.singleShot(0,lambda:self.dashboard_scroll.verticalScrollBar().setValue(0))
        QTimer.singleShot(150,lambda:self.dashboard_scroll.verticalScrollBar().setValue(0))
        QTimer.singleShot(500,self.focus_dashboard_top)
        QTimer.singleShot(2500,lambda:self.check_for_updates() if self.auto_updates.isChecked() else None)

    def focus_dashboard_top(self):
        self.source_mode.setFocus(Qt.OtherFocusReason)
        self.dashboard_scroll.verticalScrollBar().setValue(0)

    def update_group(self):
        box=QGroupBox("Application updates"); grid=QGridLayout(box)
        box.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Maximum)
        self.update_status=QLabel(f"Installed version: {APP_VERSION}")
        self.auto_updates=QCheckBox("Check automatically at startup"); self.auto_updates.setChecked(True)
        self.auto_updates.toggled.connect(lambda checked:self.settings.setValue("auto_updates",checked))
        self.check_update=QPushButton("Check for updates"); self.check_update.setObjectName("primaryButton"); self.check_update.setMinimumHeight(32); self.check_update.clicked.connect(self.check_for_updates)
        self.install_update=QPushButton("Download update"); self.install_update.setEnabled(False); self.install_update.clicked.connect(self.download_update)
        self.update_progress=QProgressBar(); self.update_progress.setRange(0,100); self.update_progress.setVisible(False)
        grid.addWidget(self.update_status,0,0); grid.addWidget(self.auto_updates,1,0)
        grid.addWidget(self.check_update,0,1,2,1,Qt.AlignVCenter); grid.addWidget(self.install_update,0,2,2,1,Qt.AlignVCenter)
        grid.addWidget(self.update_progress,2,0,1,3); grid.setColumnStretch(0,1)
        self.updater.status.connect(self.update_status.setText)
        self.updater.current.connect(self.update_current)
        self.updater.available.connect(self.update_available)
        self.updater.progress.connect(self.update_download_progress)
        self.updater.ready.connect(self.update_ready)
        self.updater.failed.connect(self.update_failed)
        return box

    def check_for_updates(self):
        self.check_update.setEnabled(False)
        self.check_update.setText("Checking…")
        self.updater.check()

    def finish_update_check(self):
        self.check_update.setEnabled(True)
        self.check_update.setText("Check for updates")

    def update_current(self,message):
        self.finish_update_check(); self.update_status.setText(message); self.install_update.setEnabled(False); self.update_progress.setVisible(False)

    def update_available(self,version,notes):
        self.finish_update_check()
        self.update_status.setText(f"Version {version} is available")
        self.install_update.setText(f"Download {version}"); self.install_update.setEnabled(True)
        self.install_update.setToolTip(notes[:1000])

    def download_update(self):
        if self.state.running:
            QMessageBox.information(self,"Match active","Pause or finish the active match before installing an update.")
            return
        self.install_update.setEnabled(False); self.update_progress.setValue(0); self.update_progress.setVisible(True); self.updater.download()

    def update_download_progress(self,value): self.update_progress.setValue(value)

    def update_ready(self,path):
        self.update_progress.setValue(100); self.update_status.setText("Update verified and ready to install")
        answer=QMessageBox.question(self,"Install update","The update is verified. Close the scoreboard and install it now?")
        if answer==QMessageBox.Yes: self.updater.install()
        else:
            self.install_update.setText("Install downloaded update"); self.install_update.setEnabled(True)
            try: self.install_update.clicked.disconnect()
            except RuntimeError: pass
            self.install_update.clicked.connect(self.updater.install)

    def update_failed(self,message):
        self.finish_update_check(); self.update_status.setText(message); self.install_update.setEnabled(bool(self.updater.asset)); self.update_progress.setVisible(False)

    def connection_group(self):
        box=QGroupBox("Setup dashboard"); grid=QGridLayout(box)
        box.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Maximum)
        self.scoring_program=WheelSafeComboBox(); self.scoring_program.addItems(("KPnP/TKDScoring","Daedo/TrueScore")); self.scoring_program.currentIndexChanged.connect(self.program_changed)
        self.source_mode=WheelSafeComboBox(); self.source_mode.addItems(("Live KPNP application","Virtual KPNP equipment")); self.source_mode.currentIndexChanged.connect(self.source_changed)
        self.transport=WheelSafeComboBox(); self.transport.addItems(("Auto detect","UDP","TCP","Serial / COM"))
        self.host=QLineEdit("0.0.0.0"); self.port=WheelSafeSpinBox(); self.port.setRange(1,65535); self.port.setValue(8056); self.port.setButtonSymbols(QSpinBox.NoButtons)
        self.connect_button=QPushButton("Start live listener"); self.connect_button.setObjectName("primaryButton"); self.connect_button.clicked.connect(self.start_source)
        self.connection_status=QLabel("Not connected"); self.connection_status.setObjectName("connectionStatus"); self.connection_status.setStyleSheet("color:#f5c451;font-weight:700")
        self.connection_status.setWordWrap(False); self.connection_status.setMinimumWidth(190)
        host_hint=QLabel("IP address of the KPnP/Daedo machine"); host_hint.setObjectName("fieldHint")
        grid.addWidget(QLabel("Program"),0,0); grid.addWidget(self.scoring_program,0,1)
        grid.addWidget(host_hint,0,3)
        grid.addWidget(QLabel("Source"),1,0); grid.addWidget(self.source_mode,1,1); grid.addWidget(QLabel("Host"),1,2); grid.addWidget(self.host,1,3)
        grid.addWidget(QLabel("Protocol"),2,0); grid.addWidget(self.transport,2,1); grid.addWidget(QLabel("Port"),2,2); grid.addWidget(self.port,2,3)
        connection_row=QHBoxLayout(); connection_row.setSpacing(8); connection_row.addStretch(1); connection_row.addWidget(self.connect_button); connection_row.addWidget(self.connection_status); connection_row.addStretch(1)
        grid.addLayout(connection_row,3,0,1,4); grid.setColumnStretch(1,1); grid.setColumnStretch(3,1); return box

    def restore_settings(self):
        self.scoring_program.blockSignals(True); self.scoring_program.setCurrentIndex(self.settings.value("program",0,int)); self.scoring_program.blockSignals(False)
        self.listener=self.daedo_listener if self.scoring_program.currentIndex()==1 else self.kpnp_listener
        self.source_mode.setCurrentIndex(self.settings.value("source",0,int)); self.transport.setCurrentIndex(self.settings.value("transport",0,int)); self.host.setText(self.settings.value("host","0.0.0.0")); self.port.setValue(self.settings.value("port",9988 if self.scoring_program.currentIndex()==1 else 8056,int)); self.design.setCurrentText(self.settings.value("design","Original")); self.screen.setCurrentIndex(min(self.settings.value("screen",0,int),max(0,self.screen.count()-1))); self.auto_updates.setChecked(self.settings.value("auto_updates",True,bool)); self.manual_section.set_expanded(self.settings.value("manual_controls_expanded",True,bool)); self.design_changed(self.design.currentText())
        if self.scoring_program.currentIndex()==1 and self.port.value()==8056 and not self.settings.value("daedo_port_initialized",False,bool):
            self.port.setValue(9988); self.transport.setCurrentText("UDP"); self.settings.setValue("daedo_port_initialized",True)
        self.program_changed(self.scoring_program.currentIndex(),False)

    def save_settings(self):
        self.settings.setValue("program",self.scoring_program.currentIndex()); self.settings.setValue("source",self.source_mode.currentIndex()); self.settings.setValue("transport",self.transport.currentIndex()); self.settings.setValue("host",self.host.text()); self.settings.setValue("port",self.port.value()); self.settings.setValue("design",self.design.currentText()); self.settings.setValue("screen",self.screen.currentIndex())
        if self.source_mode.currentIndex()==1: self.settings.setValue("manual_controls_expanded",self.manual_section.toggle.isChecked())

    def design_changed(self,design): self.board.set_design(design); self.save_settings()

    def closeEvent(self,event):
        self.save_settings()
        self.kpnp_listener.stop(); self.daedo_listener.stop()
        self.simulator.disconnect_equipment()
        self.board.close()
        super().closeEvent(event)

    def program_changed(self,index,reset_defaults=True):
        previous=self.listener
        previous.stop()
        self.listener=self.daedo_listener if index==1 else self.kpnp_listener
        daedo=index==1
        current_source=self.source_mode.currentIndex()
        self.source_mode.blockSignals(True)
        self.source_mode.clear()
        self.source_mode.addItems(("Live Daedo/TrueScore application","Virtual Daedo equipment") if daedo else ("Live KPNP application","Virtual KPNP equipment"))
        self.source_mode.setCurrentIndex(max(0,current_source))
        self.source_mode.blockSignals(False)
        if hasattr(self,"sim_box"): self.sim_box.setTitle("Virtual Daedo equipment" if daedo else "Virtual KPNP equipment")
        if hasattr(self,"event_log"): self.event_log.setPlaceholderText(f"Virtual and real {'Daedo' if daedo else 'KPNP'} events appear here…")
        if daedo:
            help_text="In TkStrike: Configuration → External → External UDP Event Listeners. Add this scoreboard computer's IP address and port 9988, then Save."
            self.connect_button.setToolTip(help_text); self.connection_status.setToolTip(help_text)
        else:
            self.connect_button.setToolTip(""); self.connection_status.setToolTip("")
        if reset_defaults:
            self.transport.setCurrentText("UDP" if daedo else "Auto detect")
            self.port.setValue(9988 if daedo else 8056)
            if daedo: self.settings.setValue("daedo_port_initialized",True)
        self.source_changed(self.source_mode.currentIndex())

    def source_changed(self,index):
        virtual=index==1
        self.listener.stop()
        self.manual_section.set_expanded(self.settings.value("manual_controls_expanded",True,bool) if virtual else False)
        if hasattr(self,"sim_box"): self.sim_box.setVisible(virtual)
        for group in getattr(self,"manual_data_groups",()): group.setEnabled(virtual)
        self.host.setEnabled(not virtual); self.port.setEnabled(not virtual); self.transport.setEnabled(not virtual)
        self.connect_button.setText("Connect virtual equipment" if virtual else "Start live listener")
        program="Daedo" if self.scoring_program.currentIndex()==1 else "KPNP"
        self.connection_status.setText(f"Ready for virtual {program} testing" if virtual else f"Live {program} decoder ready")
        self.save_settings()

    def start_source(self):
        program="Daedo" if self.scoring_program.currentIndex()==1 else "KPNP"
        if self.source_mode.currentIndex()==1:
            self.simulator.connect_equipment(); self.sim_connected.setChecked(True); self.connection_status.setText(f"Virtual {program} connected"); self.connection_status.setStyleSheet("color:#35c759;font-weight:700")
        else:
            transport=self.transport.currentText()
            if transport not in ("Auto detect","UDP","TCP"):
                self.connection_status.setText(f"{transport} capture is not implemented yet"); self.connection_status.setStyleSheet("color:#ff9f0a;font-weight:700")
            else:
                host="0.0.0.0"
                if transport=="TCP": self.listener.start_tcp(host,self.port.value())
                else: self.listener.start_udp(host,self.port.value())
        self.save_settings()

    def listener_status(self,message):
        self.connection_status.setText(message)
        good=message.startswith(("Listening","Waiting","KPNP connected","Daedo connected"))
        self.connection_status.setStyleSheet(f"color:{'#35c759' if good else '#ff9f0a'};font-weight:700")
        if hasattr(self,"event_log"):
            self.event_log.append(f"[Listener] {message}")
            if message.startswith(("Listening","Waiting")):
                self.event_log.append(f"[Capture] {self.listener.capture_path}")

    def route_simulator_packet(self,packet):
        self.listener.feed(packet)

    def copy_event_log(self):
        QApplication.clipboard().setText(self.event_log.toPlainText())

    def move_output(self):
        screens=QApplication.screens(); index=self.screen.currentIndex()
        if 0<=index<len(screens):
            self.board.showNormal(); self.board.move(screens[index].availableGeometry().topLeft()); self.board.show(); self.board.raise_(); self.sync_output_button(); self.save_settings()

    def toggle_output(self):
        if self.board.isVisible(): self.board.hide()
        else: self.show_output()
        self.sync_output_button()

    def toggle_borderless_output(self):
        self.board.toggle_borderless(); self.sync_output_button()

    def sync_output_button(self):
        self.show_output_button.setText("Hide output" if self.board.isVisible() else "Show output")

    def side_group(self,title,side):
        box=QGroupBox(title); form=QGridLayout(box); form.setHorizontalSpacing(8); form.setVerticalSpacing(7)
        self.manual_data_groups.append(box)
        countries=WheelSafeComboBox(); countries.setEditable(True); countries.setInsertPolicy(QComboBox.NoInsert)
        selected=0
        for index,country in enumerate(sorted(pycountry.countries,key=lambda c:c.name)):
            alpha3=getattr(country,"alpha_3",""); countries.addItem(f"{country.name} ({alpha3})",(country.alpha_2,alpha3,country.name.upper()))
            if alpha3==side.country: selected=index
        countries.setCurrentIndex(selected); countries.currentIndexChanged.connect(lambda i,s=side,c=countries:self.select_country(s,c.itemData(i)))
        nation=QLineEdit(side.nation); nation.textChanged.connect(lambda v,s=side:(setattr(s,"nation",v.upper()),self.state.changed.emit()))
        first=QLineEdit(side.first); first.textChanged.connect(lambda v,s=side:(setattr(s,"first",v.upper()),self.state.changed.emit()))
        last=QLineEdit(side.last); last.textChanged.connect(lambda v,s=side:(setattr(s,"last",v.upper()),self.state.changed.emit()))
        for field in (countries,nation,first,last): field.setMinimumWidth(70)
        form.addWidget(QLabel("Country"),0,0); form.addWidget(countries,0,1); form.addWidget(QLabel("Nation"),0,2); form.addWidget(nation,0,3)
        form.addWidget(QLabel("First name"),1,0); form.addWidget(first,1,1); form.addWidget(QLabel("Last name"),1,2); form.addWidget(last,1,3)
        scoring=[]
        for label,field,maximum in (("Score","score",999),("Rounds won","rounds",3),("Gam-jeom","gamjeom",5)):
            spin=WheelSafeSpinBox(); spin.setRange(0,maximum); spin.setValue(getattr(side,field)); spin.setMinimumWidth(70); spin.setMaximumWidth(82); spin.valueChanged.connect(lambda v,s=side,f=field:(setattr(s,f,v),self.state.changed.emit())); scoring.append((label,spin))
        score_row=QHBoxLayout(); score_row.setContentsMargins(8,0,8,0); score_row.setSpacing(5); score_row.addStretch(1)
        for index,(label,spin) in enumerate(scoring):
            score_row.addWidget(QLabel(label)); score_row.addWidget(spin)
            if index < len(scoring)-1: score_row.addSpacing(9)
        score_row.addStretch(1); form.addLayout(score_row,2,0,1,4)
        form.setColumnStretch(1,1); form.setColumnStretch(3,1)
        return box

    def select_country(self,side,data):
        if data:
            side.alpha2,side.country,side.nation=data; self.state.changed.emit()

    def set_clock(self): self.state.update(seconds=self.minutes.value()*60+self.seconds.value())
    def clock_toggle(self,on): self.state.running=on; self.start.setText("Pause clock" if on else "Start clock")
    def reset_clock(self): self.state.running=False; self.start.setChecked(False); self.minutes.setValue(1); self.seconds.setValue(30); self.set_clock()
    def finish_fight(self):
        self.start.blockSignals(True); self.start.setChecked(False); self.start.setText("Start clock"); self.start.blockSignals(False)
        for widget,value in ((self.match_number,101),(self.round,1),(self.minutes,1),(self.seconds,30)):
            widget.blockSignals(True); widget.setValue(value); widget.blockSignals(False)
        self.state.reset_defaults()
    def clock_step(self):
        if self.source_mode.currentIndex()==0:
            return
        if self.state.running and self.state.seconds>0:
            self.state.seconds-=1; self.minutes.blockSignals(True); self.seconds.blockSignals(True); self.minutes.setValue(self.state.seconds//60); self.seconds.setValue(self.state.seconds%60); self.minutes.blockSignals(False); self.seconds.blockSignals(False); self.state.changed.emit()
        elif self.state.running: self.start.setChecked(False)
    def anim_step(self):
        self.state.tick()
    def simulator_group(self):
        box=QGroupBox("Virtual KPNP equipment"); layout=QVBoxLayout(box)
        top=QHBoxLayout(); self.sim_connected=QCheckBox("Connected"); self.sim_connected.toggled.connect(lambda on:self.simulator.connect_equipment() if on else self.simulator.disconnect_equipment())
        self.sim_auto=QCheckBox("Automatic match"); self.sim_auto.toggled.connect(self.simulator.set_automatic)
        self.sim_strength=WheelSafeSpinBox(); self.sim_strength.setRange(1,100); self.sim_strength.setValue(70); self.sim_strength.setSuffix("% PSS")
        top.addWidget(self.sim_connected); top.addWidget(self.sim_auto); top.addWidget(QLabel("Hit strength")); top.addWidget(self.sim_strength); layout.addLayout(top)
        hits=QHBoxLayout()
        for label,callback in (("Blue hit",lambda:self.simulator.hit("blue",self.sim_strength.value())),("Simultaneous hit",lambda:self.simulator.simultaneous_hit(self.sim_strength.value())),("Red hit",lambda:self.simulator.hit("red",self.sim_strength.value()))):
            button=QPushButton(label); button.clicked.connect(callback); hits.addWidget(button)
        layout.addLayout(hits)
        events=QGridLayout()
        actions=(("Blue +1",lambda:self.simulator.score("blue",1)),("Blue +2",lambda:self.simulator.score("blue",2)),("Blue Gam-jeom",lambda:self.simulator.gamjeom("blue")),("Blue round",lambda:self.simulator.round_win("blue")),
                 ("Red +1",lambda:self.simulator.score("red",1)),("Red +2",lambda:self.simulator.score("red",2)),("Red Gam-jeom",lambda:self.simulator.gamjeom("red")),("Red round",lambda:self.simulator.round_win("red")),
                 ("Clock start",lambda:self.simulator.clock("start")),("Clock pause",lambda:self.simulator.clock("pause")),("Clock reset",lambda:self.simulator.clock("reset")),("Next round",self.simulator.next_round))
        for index,(label,callback) in enumerate(actions):
            button=QPushButton(label); button.clicked.connect(callback); events.addWidget(button,index//4,index%4)
        layout.addLayout(events); return box

    def apply_packet(self,packet):
        event=packet.get("event"); side_name=packet.get("side")
        side=getattr(self.state,side_name,None) if side_name in ("blue","red") else None
        if event in ("result","fight_finished","fight\\_finished"): self.finish_fight()
        elif event=="state": self.state.update(**{key:value for key,value in packet.items() if key!="event"})
        elif event=="pss_hit" and side: self.state.impact(side_name,packet.get("strength",0))
        elif event=="score" and side: side.score=max(0,side.score+packet.get("delta",0)); self.state.changed.emit()
        elif event=="gamjeom" and side: side.gamjeom=max(0,min(5,side.gamjeom+packet.get("delta",0))); self.state.changed.emit()
        elif event=="round_win" and side: side.rounds=max(0,min(3,side.rounds+packet.get("delta",0))); self.state.changed.emit()
        elif event=="clock":
            action=packet.get("action")
            if action=="start": self.start.setChecked(True)
            elif action=="pause": self.start.setChecked(False)
            elif action=="reset": self.reset_clock()
        elif event=="next_round": self.round.setValue(min(3,self.state.round+1))
        elif event=="match":
            try: self.match_number.setValue(int(packet.get("match_number")))
            except (TypeError,ValueError): pass
        elif event=="connection": self.sim_connected.blockSignals(True); self.sim_connected.setChecked(bool(packet.get("connected"))); self.sim_connected.blockSignals(False)
        if hasattr(self,"event_log"):
            self.event_log.append(json.dumps(packet,separators=(",",":")))
    def show_output(self): self.board.show(); self.board.raise_(); self.board.activateWindow(); self.sync_output_button()


def main():
    app=QApplication(sys.argv); app.setWindowIcon(QIcon(str(asset_path("app.ico")))); app.setStyle("Fusion"); stylesheet="""
        QMainWindow#operatorWindow, QWidget#dashboardPage { background:#0d1117; color:#e7edf5; }
        QScrollArea#dashboardScroll { background:#0d1117; border:none; }
        QWidget { color:#dce4ee; font:10pt 'Segoe UI'; }
        QFrame#appHeader { background:#151b24; border:1px solid #263142; border-radius:12px; }
        QLabel#appTitle { color:#ffffff; font-size:18pt; font-weight:750; }
        QLabel#appSubtitle { color:#8391a5; font-size:9pt; }
        QLabel#fieldHint { color:#8f9aaa; font-size:8pt; font-weight:500; }
        QLabel#versionBadge { color:#83c9ff; background:#102a40; border:1px solid #24577b; border-radius:10px; padding:5px 10px; font-size:8pt; font-weight:700; }
        QGroupBox { background:#151a22; border:1px solid #2a3443; border-radius:10px; margin-top:13px; padding:16px 12px 12px; font-weight:700; color:#f3f6fa; }
        QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 6px; color:#aebbd0; }
        QLineEdit, QComboBox, QSpinBox, QTextEdit { background:#0f141b; border:1px solid #303c4d; border-radius:6px; padding:6px 8px; color:#eef4fb; selection-background-color:#1978b8; }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus { border:1px solid #3da9f5; }
        QComboBox::drop-down { border:none; width:24px; }
        QComboBox::down-arrow { image:url(__DOWN_ARROW__); width:10px; height:7px; }
        QSpinBox { padding-right:22px; }
        QSpinBox::up-button, QSpinBox::down-button { background:#1d2632; border-left:1px solid #303c4d; width:18px; }
        QSpinBox::up-button { border-top-right-radius:5px; border-bottom:1px solid #303c4d; }
        QSpinBox::down-button { border-bottom-right-radius:5px; }
        QSpinBox::up-arrow { image:url(__UP_ARROW__); width:10px; height:7px; }
        QSpinBox::down-arrow { image:url(__DOWN_ARROW__); width:10px; height:7px; }
        QPushButton { background:#242d3a; border:1px solid #354256; border-radius:7px; padding:7px 12px; color:#e8eef6; font-weight:600; }
        QPushButton:hover { background:#303b4b; border-color:#4d6078; }
        QPushButton:pressed { background:#1d2530; }
        QPushButton:disabled { color:#687487; background:#171c24; border-color:#252d38; }
        QPushButton#primaryButton { background:#1676b8; border-color:#2999e6; color:white; }
        QPushButton#primaryButton:hover { background:#218bd1; }
        QToolButton#sectionToggle { background:#151a22; border:1px solid #2a3443; border-radius:9px; padding:9px 12px; color:#f3f6fa; font-weight:700; text-align:left; }
        QToolButton#sectionToggle:hover { background:#1b222d; border-color:#3d4b60; }
        QProgressBar { background:#0f141b; border:1px solid #303c4d; border-radius:5px; text-align:center; }
        QProgressBar::chunk { background:#269ce1; border-radius:4px; }
        QCheckBox { spacing:7px; }
        QTextEdit { font-family:'Cascadia Mono','Consolas'; font-size:9pt; }
        QScrollBar:vertical { background:#0d1117; width:10px; margin:0; }
        QScrollBar::handle:vertical { background:#354255; border-radius:5px; min-height:28px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
    """
    stylesheet=stylesheet.replace("__UP_ARROW__",str(asset_path("spin-up.svg")).replace("\\","/")).replace("__DOWN_ARROW__",str(asset_path("spin-down.svg")).replace("\\","/"))
    app.setStyleSheet(stylesheet)
    state=MatchState(); board=Scoreboard(state); operator=Operator(state,board); board.show(); operator.show(); sys.exit(app.exec())


if __name__=="__main__": main()
