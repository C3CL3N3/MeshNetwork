# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

import unittest

from net.neighbor_table import NeighborTable


class NeighborTableTests(unittest.TestCase):
    def test_fixed_capacity_without_eviction(self):
        table = NeighborTable(capacity=2)
        self.assertIsNotNone(table.get_or_add(1, allow_evict=False))
        self.assertIsNotNone(table.get_or_add(2, allow_evict=False))
        self.assertIsNone(table.get_or_add(3, allow_evict=False))
        self.assertEqual(len(table), 2)

    def test_fixed_capacity_with_oldest_eviction(self):
        table = NeighborTable(capacity=2)
        a = table.get_or_add(1)
        b = table.get_or_add(2)
        a.touch(now_ms=100)
        b.touch(now_ms=200)

        c = table.get_or_add(3, allow_evict=True)
        self.assertIsNotNone(c)
        self.assertIsNone(table.find(1))
        self.assertIsNotNone(table.find(2))
        self.assertIsNotNone(table.find(3))

    def test_exponential_smoothing_and_delivery_metrics(self):
        table = NeighborTable(capacity=4, alpha=0.5, window_size=4)
        table.update_link_sample(10, rssi_dbm=-100, snr_db=0, delivered=True, retries=0, airtime_ms=20, queue_delay_ms=5, now_ms=100)
        e = table.update_link_sample(10, rssi_dbm=-80, snr_db=10, delivered=False, retries=2, airtime_ms=10, queue_delay_ms=3, now_ms=200)

        self.assertIsNotNone(e)
        self.assertAlmostEqual(e.avg_rssi_dbm, -90.0)
        self.assertAlmostEqual(e.avg_snr_db, 5.0)
        self.assertAlmostEqual(e.pdr, 0.5)
        self.assertAlmostEqual(e.retry_rate, 1.0)
        self.assertGreater(e.est_airtime_ms, 0.0)
        self.assertGreater(e.queue_delay_ms, 0.0)
        self.assertEqual(e.last_seen_ms, 200)

    def test_prune_stale(self):
        table = NeighborTable(capacity=4)
        a = table.get_or_add(1)
        b = table.get_or_add(2)
        a.touch(now_ms=100)
        b.touch(now_ms=1000)

        removed = table.prune_stale(max_age_ms=500, now_ms=1400)
        self.assertEqual(removed, 1)
        self.assertIsNone(table.find(1))
        self.assertIsNotNone(table.find(2))


if __name__ == "__main__":
    unittest.main()
