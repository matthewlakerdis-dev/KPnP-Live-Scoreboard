"""Deterministic theme checks; run with QT_QPA_PLATFORM=offscreen."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from PySide6.QtGui import QColor, QFontDatabase, QPalette
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QCheckBox, QGroupBox, QLabel,
                              QLineEdit, QListView, QPushButton, QSpinBox,
                              QVBoxLayout, QWidget)
from main import WheelSafeComboBox, apply_dashboard_theme
import main


def contrast(first, second):
    def luminance(colour):
        channels = [colour.redF(), colour.greenF(), colour.blueF()]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
        return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))
    a, b = sorted((luminance(first), luminance(second)))
    return (b + .05) / (a + .05)


class DashboardThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # The Windows offscreen plugin does not enumerate installed fonts.
        # Supply the same Segoe UI faces the native Windows plugin discovers.
        font_root = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
            path = font_root / name
            if path.exists(): QFontDatabase.addApplicationFont(str(path))

    def test_all_palette_groups_ignore_host_colours(self):
        for host_background in ("white", "black", "yellow"):
            host = QPalette()
            host.setColor(QPalette.Base, QColor(host_background))
            host.setColor(QPalette.Text, QColor("white"))
            self.app.setPalette(host)
            apply_dashboard_theme(self.app)
            palette = self.app.palette()
            for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
                for foreground, background in ((QPalette.Text, QPalette.Base),
                                              (QPalette.WindowText, QPalette.Window),
                                              (QPalette.ButtonText, QPalette.Button),
                                              (QPalette.HighlightedText, QPalette.Highlight),
                                              (QPalette.ToolTipText, QPalette.ToolTipBase)):
                    self.assertGreaterEqual(contrast(palette.color(group, foreground),
                                                     palette.color(group, background)), 4.5)

    def test_popups_and_disabled_fields(self):
        apply_dashboard_theme(self.app)
        window = QWidget()
        layout = QVBoxLayout(window)
        box = QGroupBox("Readability check — active and disabled controls")
        fields = QVBoxLayout(box)
        combo = WheelSafeComboBox()
        combo.addItems(["KPnP/TKDScoring", "Daedo/TrueScore", "Minimal Broadcast"])
        fields.addWidget(QLabel("Scoring program"))
        fields.addWidget(combo)
        hint = QLabel("IP address of the KPnP/Daedo machine")
        hint.setObjectName("fieldHint")
        fields.addWidget(hint)
        fields.addWidget(QLineEdit("192.168.4.168"))
        disabled = QLineEdit("Live data — read only")
        disabled.setEnabled(False)
        fields.addWidget(disabled)
        spin = QSpinBox()
        spin.setRange(0, 9999)
        spin.setValue(8056)
        fields.addWidget(spin)
        check = QCheckBox("Check automatically at startup")
        check.setChecked(True)
        fields.addWidget(check)
        for enabled in (True, False):
            button = QPushButton("Check for updates" if enabled else "No update available")
            button.setObjectName("primaryButton")
            button.setEnabled(enabled)
            fields.addWidget(button)
        layout.addWidget(box)
        window.resize(540, 480)
        window.show()
        self.app.processEvents()
        self.assertIsInstance(combo.view(), QListView)
        folder = os.environ.get("THEME_QA_DIR")
        if folder:
            Path(folder).mkdir(parents=True, exist_ok=True)
            window.grab().save(str(Path(folder) / "controls.png"))
        combo.showPopup()
        self.app.processEvents()
        palette = combo.view().palette()
        self.assertGreaterEqual(contrast(palette.color(QPalette.Text), palette.color(QPalette.Base)), 4.5)
        if folder:
            combo.view().window().grab().save(str(Path(folder) / "dropdown.png"))
        combo.hidePopup()
        window.close()

    def test_operator_section_groups(self):
        apply_dashboard_theme(self.app)
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / "dashboard.ini"), QSettings.IniFormat)
            settings.setValue("auto_updates", False)
            with patch.object(main, "QSettings", return_value=settings):
                board = main.Scoreboard(main.MatchState())
                operator = main.Operator(board.state, board)
                try:
                    operator.source_mode.setCurrentIndex(1)
                    operator.manual_section.set_expanded(True)
                    operator.show()
                    self.app.processEvents()
                    self.assertEqual(operator.listener_box.title(), "Listener output")
                    self.assertEqual(operator.results_box.title(), "Scoreboard results")
                    for group in operator.manual_data_groups:
                        self.assertTrue(operator.results_box.isAncestorOf(group))
                    self.assertTrue(operator.listener_box.isAncestorOf(operator.event_log))
                    self.assertLessEqual(operator.results_box.width(), operator.dashboard_scroll.viewport().width())
                    match = operator.manual_data_groups[-1]
                    match_bottom = match.mapTo(operator.results_box, match.rect().bottomLeft()).y()
                    self.assertGreaterEqual(operator.results_box.height() - match_bottom, 24)
                    expanded_height = operator.results_box.height()
                    operator.manual_section.toggle.click()
                    self.app.processEvents()
                    self.assertFalse(operator.manual_section.content.isVisible())
                    self.assertTrue(operator.manual_section.toggle.isVisible())
                    self.assertEqual(operator.manual_section.toggle.arrowType(), Qt.RightArrow)
                    self.assertLess(operator.results_box.height(), expanded_height)
                    QTest.keyClick(operator.manual_section.toggle, Qt.Key_Space)
                    self.app.processEvents()
                    self.assertTrue(operator.manual_section.content.isVisible())
                    self.assertEqual(operator.manual_section.toggle.arrowType(), Qt.DownArrow)
                    operator.event_log.setPlainText("Listener test")
                    buttons = {b.text(): b for b in operator.listener_box.findChildren(QPushButton)}
                    buttons["Copy all"].click()
                    self.assertEqual(self.app.clipboard().text(), "Listener test")
                    buttons["Clear"].click()
                    self.assertEqual(operator.event_log.toPlainText(), "")
                    qa = os.environ.get("THEME_QA_DIR")
                    if qa:
                        Path(qa).mkdir(parents=True, exist_ok=True)
                        operator.results_box.grab().save(str(Path(qa) / "results.png"))
                        operator.listener_box.grab().save(str(Path(qa) / "listener.png"))
                    operator.source_mode.setCurrentIndex(0)
                    self.assertFalse(operator.manual_section.toggle.isChecked())
                    self.assertFalse(operator.manual_section.content.isVisible())
                    self.assertTrue(operator.manual_section.toggle.isVisible())
                    if qa:
                        self.app.processEvents()
                        operator.results_box.grab().save(str(Path(qa) / "results-collapsed.png"))
                    self.assertTrue(all(not group.isEnabled() for group in operator.manual_data_groups))
                finally:
                    operator.close()
                    self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
