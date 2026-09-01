"""Regression tests for commands found in real TKDScoring captures."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from PySide6.QtCore import QCoreApplication
from kpnp_listener import KPNPListener


class KPNPListenerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def packets_for(self, *messages):
        listener = KPNPListener()
        packets = []
        listener.packet.connect(packets.append)
        for message in messages:
            listener._decode(message)
        return packets

    def test_intermission_show_ticks_and_hide(self):
        packets = self.packets_for("ij0;1:00;show", "ij0;0:59", "ij0;1:00;hide")
        self.assertEqual(packets[0], {"event": "state", "running": False,
                                     "timeout_active": True, "seconds": 60})
        self.assertEqual(packets[1]["seconds"], 59)
        self.assertTrue(packets[1]["timeout_active"])
        self.assertFalse(packets[2]["timeout_active"])

    def test_stop_end_clock_accepts_period_separator(self):
        packets = self.packets_for("clk;0.00;stopEnd;")
        self.assertEqual(packets, [{"event": "state", "seconds": 0,
                                    "running": False}])

    def test_hit_levels_drive_the_correct_pss_meter(self):
        packets = self.packets_for("hl2;13", "hl1;14")
        self.assertEqual(packets[0], {"event": "pss_hit", "side": "red",
                                     "strength": 13})
        self.assertEqual(packets[1], {"event": "pss_hit", "side": "blue",
                                     "strength": 14})

    def test_round_state_is_a_score_fallback(self):
        packets = self.packets_for("s11;6;s21;6;s12; 8;s22; 7;s13;0;s23;0")
        self.assertEqual(packets, [{"event": "state", "blue_score": 8,
                                    "red_score": 7}])

    def test_point_awards_update_immediately_then_reconcile(self):
        packets = self.packets_for(
            "s11;6;s21;6;s12; 0;s22; 4;s13;0;s23;0",
            "pt1;3",
            "s11;6;s21;6;s12; 3;s22; 4;s13;0;s23;0",
            "sc1; 3;sc2; 4",
        )
        self.assertEqual(packets[1], {"event": "score", "side": "blue",
                                      "delta": 3})
        self.assertEqual(packets[-1], {"event": "state", "blue_score": 3,
                                       "red_score": 4})

    def test_reset_controls_clear_pss_without_erasing_scores(self):
        for packet in self.packets_for("rst;1;st1;0;2;0;0;0;0;st2;0;2;0;0;0;0;", "rsr;"):
            self.assertEqual(packet, {"event": "state", "blue_pss": 0.0,
                                      "red_pss": 0.0, "blue_peak": 0.0,
                                      "red_peak": 0.0})


if __name__ == "__main__":
    unittest.main()
