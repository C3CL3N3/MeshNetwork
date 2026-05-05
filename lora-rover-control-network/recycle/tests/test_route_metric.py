# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

import unittest

from net.neighbor_table import NeighborTable
from net.route_metric import RouteScorer, score_entry, score_speed, score_throughput


def _entry(node_id, *, pdr, snr, airtime, queue, retries, hop, sf):
    table = NeighborTable(capacity=2)
    e = table.get_or_add(node_id)
    e.pdr = float(pdr)
    e.avg_snr_db = float(snr)
    e.est_airtime_ms = float(airtime)
    e.queue_delay_ms = float(queue)
    e.retry_rate = float(retries)
    e.hop_level = int(hop)
    e.current_sf = int(sf)
    return e


class RouteMetricTests(unittest.TestCase):
    def test_speed_prefers_lower_delay_profile(self):
        fast = _entry(1, pdr=0.92, snr=8, airtime=12, queue=2, retries=0.1, hop=1, sf=8)
        slow = _entry(2, pdr=0.95, snr=9, airtime=60, queue=10, retries=0.1, hop=1, sf=11)
        self.assertGreater(score_speed(fast), score_speed(slow))

    def test_throughput_prefers_lower_sf_stable_link(self):
        a = _entry(3, pdr=0.90, snr=6, airtime=30, queue=3, retries=0.2, hop=2, sf=8)
        b = _entry(4, pdr=0.90, snr=8, airtime=40, queue=3, retries=0.2, hop=2, sf=11)
        self.assertGreater(score_throughput(a), score_throughput(b))

    def test_runtime_mode_switch(self):
        speed_candidate = _entry(5, pdr=0.90, snr=9, airtime=10, queue=1, retries=0.5, hop=1, sf=9)
        throughput_candidate = _entry(6, pdr=0.96, snr=7, airtime=25, queue=2, retries=0.0, hop=1, sf=7)

        scorer = RouteScorer(mode="speed")
        speed_diff = scorer.score(speed_candidate) - scorer.score(throughput_candidate)

        scorer.set_mode("throughput")
        throughput_diff = scorer.score(speed_candidate) - scorer.score(throughput_candidate)

        self.assertNotEqual(speed_diff, throughput_diff)

    def test_score_entry_invalid_mode(self):
        e = _entry(7, pdr=0.9, snr=8, airtime=12, queue=1, retries=0.0, hop=1, sf=8)
        with self.assertRaises(ValueError):
            score_entry(e, mode="unknown")


if __name__ == "__main__":
    unittest.main()
