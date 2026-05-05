# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

import unittest

from net.neighbor_table import NeighborTable
from net.sf_controller import SFController


class SFControllerTests(unittest.TestCase):
    def _entry(self, sf=9, min_sf=7, max_sf=12, pdr=1.0, retry_rate=0.0, snr=10.0):
        table = NeighborTable(capacity=2)
        entry = table.get_or_add(100)
        entry.current_sf = sf
        entry.min_sf = min_sf
        entry.max_sf = max_sf
        entry.pdr = pdr
        entry.retry_rate = retry_rate
        entry.avg_snr_db = snr
        return entry

    def test_raise_sf_fast_on_reliability_drop(self):
        ctrl = SFController(n_up=2, n_down=5, cooldown_ms=0)
        entry = self._entry(sf=9, pdr=0.80, retry_rate=1.2, snr=1)

        s1 = ctrl.suggest(entry, now_ms=100)
        self.assertEqual(s1["action"], "hold")

        s2 = ctrl.suggest(entry, now_ms=200)
        self.assertEqual(s2["action"], "set_sf")
        self.assertEqual(s2["sf"], 10)

    def test_lower_sf_slow_on_stable_link(self):
        ctrl = SFController(n_up=2, n_down=3, cooldown_ms=0, snr_down_threshold=5.0)
        entry = self._entry(sf=9, pdr=0.99, retry_rate=0.0, snr=8)

        ctrl.suggest(entry, now_ms=100)
        ctrl.suggest(entry, now_ms=200)
        s3 = ctrl.suggest(entry, now_ms=300)

        self.assertEqual(s3["action"], "set_sf")
        self.assertEqual(s3["sf"], 8)

    def test_cooldown_blocks_rapid_repeated_changes(self):
        ctrl = SFController(n_up=1, n_down=1, cooldown_ms=1000)
        entry = self._entry(sf=9, pdr=0.80, retry_rate=1.5, snr=0)

        s1 = ctrl.suggest(entry, now_ms=100)
        self.assertEqual(s1["action"], "set_sf")

        # Still poor, but should be cooldown hold.
        s2 = ctrl.suggest(entry, now_ms=500)
        self.assertEqual(s2["action"], "hold")

        s3 = ctrl.suggest(entry, now_ms=1300)
        self.assertEqual(s3["action"], "set_sf")

    def test_probe_generated_for_stable_link(self):
        ctrl = SFController(n_up=3, n_down=99, cooldown_ms=0, probe_interval_packets=3)
        entry = self._entry(sf=9, pdr=0.99, retry_rate=0.0, snr=10)

        a1 = ctrl.suggest(entry, now_ms=100)
        a2 = ctrl.suggest(entry, now_ms=200)
        a3 = ctrl.suggest(entry, now_ms=300)

        self.assertEqual(a1["action"], "hold")
        self.assertEqual(a2["action"], "hold")
        self.assertEqual(a3["action"], "probe")
        self.assertEqual(a3["sf"], 8)

    def test_apply_suggestion_updates_neighbor(self):
        ctrl = SFController(n_up=1, cooldown_ms=0)
        entry = self._entry(sf=9, pdr=0.8, retry_rate=2.0, snr=0)
        suggestion = ctrl.suggest(entry, now_ms=100)

        self.assertTrue(ctrl.apply_suggestion(entry, suggestion, now_ms=110))
        self.assertEqual(entry.current_sf, 10)
        self.assertEqual(entry.last_sf_change_ms, 110)


if __name__ == "__main__":
    unittest.main()
