# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

import unittest

from net.neighbor_table import NeighborTable
from net.topology import TopologyManager


def _entry(table, node_id, *, pdr, snr, airtime, queue, child, hop, seen_ms):
    e = table.get_or_add(node_id)
    e.pdr = float(pdr)
    e.avg_snr_db = float(snr)
    e.est_airtime_ms = float(airtime)
    e.queue_delay_ms = float(queue)
    e.child_count = int(child)
    e.hop_level = int(hop)
    e.last_seen_ms = int(seen_ms)
    return e


class TopologyManagerTests(unittest.TestCase):
    def test_selects_best_scored_parent(self):
        table = NeighborTable(capacity=4)
        _entry(table, 11, pdr=0.70, snr=2, airtime=30, queue=8, child=3, hop=2, seen_ms=1000)
        _entry(table, 12, pdr=0.95, snr=9, airtime=10, queue=2, child=1, hop=1, seen_ms=1000)

        mgr = TopologyManager(min_switch_interval_ms=0)
        parent = mgr.update(table, now_ms=1500)

        self.assertEqual(parent, 12)
        self.assertFalse(mgr.rejoin_required)

    def test_hysteresis_prevents_small_improvement_switch(self):
        table = NeighborTable(capacity=4)
        a = _entry(table, 21, pdr=0.90, snr=8, airtime=12, queue=2, child=1, hop=1, seen_ms=1000)
        b = _entry(table, 22, pdr=0.91, snr=8, airtime=12, queue=2, child=1, hop=1, seen_ms=1000)

        mgr = TopologyManager(hysteresis_margin=0.5, min_switch_interval_ms=0)
        mgr.parent_id = 21
        mgr.parent_score = mgr.score_entry(a)

        parent = mgr.update(table, now_ms=2000)
        self.assertEqual(parent, 21)

        # Make competitor clearly better than hysteresis margin.
        b.pdr = 1.0
        b.avg_snr_db = 12.0
        parent = mgr.update(table, now_ms=2500)
        self.assertEqual(parent, 22)

    def test_min_switch_interval_blocks_immediate_switch(self):
        table = NeighborTable(capacity=4)
        a = _entry(table, 31, pdr=0.9, snr=8, airtime=10, queue=2, child=1, hop=1, seen_ms=1000)
        _entry(table, 32, pdr=1.0, snr=12, airtime=8, queue=1, child=0, hop=1, seen_ms=1000)

        mgr = TopologyManager(hysteresis_margin=0.1, min_switch_interval_ms=1000)
        mgr.parent_id = 31
        mgr.parent_score = mgr.score_entry(a)
        mgr.last_switch_ms = 3000

        parent = mgr.update(table, now_ms=3500)
        self.assertEqual(parent, 31)

        parent = mgr.update(table, now_ms=4100)
        self.assertEqual(parent, 32)

    def test_broken_link_and_rejoin_flag(self):
        table = NeighborTable(capacity=4)
        _entry(table, 41, pdr=0.9, snr=8, airtime=10, queue=2, child=1, hop=1, seen_ms=100)

        mgr = TopologyManager(broken_link_timeout_ms=500, min_switch_interval_ms=0)
        mgr.parent_id = 41

        # Candidate becomes stale and no alternative exists.
        parent = mgr.update(table, now_ms=1000)
        self.assertIsNone(parent)
        self.assertTrue(mgr.rejoin_required)
        self.assertEqual(mgr.rejoin_count, 1)
        self.assertTrue(mgr.consume_rejoin_flag())
        self.assertFalse(mgr.rejoin_required)


if __name__ == "__main__":
    unittest.main()
