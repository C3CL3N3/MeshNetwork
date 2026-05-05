# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

import unittest

from net.control_cycle import LinkRouteController
from net.neighbor_table import NeighborTable
from net.sf_controller import SFController
from net.topology import TopologyManager


def _seed_entry(table, node_id, *, pdr, snr, airtime, queue, retries, hop, sf, seen_ms):
    e = table.get_or_add(node_id)
    e.pdr = float(pdr)
    e.avg_snr_db = float(snr)
    e.est_airtime_ms = float(airtime)
    e.queue_delay_ms = float(queue)
    e.retry_rate = float(retries)
    e.hop_level = int(hop)
    e.current_sf = int(sf)
    e.last_seen_ms = int(seen_ms)
    return e


class ControlCycleTests(unittest.TestCase):
    def test_exact_stage_order(self):
        table = NeighborTable(capacity=4)
        _seed_entry(table, 1, pdr=0.9, snr=8, airtime=20, queue=2, retries=0.1, hop=1, sf=9, seen_ms=100)
        _seed_entry(table, 2, pdr=0.92, snr=7, airtime=15, queue=2, retries=0.1, hop=2, sf=8, seen_ms=100)

        topo = TopologyManager(min_switch_interval_ms=0, hysteresis_margin=0.0)
        sf = SFController(n_up=2, n_down=3, cooldown_ms=0)
        cycle = LinkRouteController(topo, sf)

        result = cycle.run_cycle(table, now_ms=200)

        self.assertEqual(
            result["stage_order"],
            [
                "discover_neighbors",
                "estimate_link_sf",
                "convert_sf_to_cost",
                "choose_route",
                "fine_tune_selected_links",
            ],
        )

    def test_chosen_parent_exists_and_scores_present(self):
        table = NeighborTable(capacity=4)
        _seed_entry(table, 1, pdr=0.7, snr=2, airtime=70, queue=10, retries=0.4, hop=1, sf=11, seen_ms=100)
        _seed_entry(table, 2, pdr=0.95, snr=9, airtime=15, queue=2, retries=0.0, hop=1, sf=8, seen_ms=100)

        topo = TopologyManager(min_switch_interval_ms=0, hysteresis_margin=0.0)
        sf = SFController(n_up=2, n_down=3, cooldown_ms=0)
        cycle = LinkRouteController(topo, sf, mode="speed")

        result = cycle.run_cycle(table, now_ms=300)

        self.assertIn(result["chosen_parent"], (1, 2))
        self.assertIn(1, result["mode_scores"])
        self.assertIn(2, result["mode_scores"])

    def test_sf_finetune_only_on_selected_link(self):
        table = NeighborTable(capacity=4)
        e1 = _seed_entry(table, 1, pdr=0.80, snr=3, airtime=18, queue=2, retries=1.5, hop=1, sf=9, seen_ms=100)
        e2 = _seed_entry(table, 2, pdr=0.99, snr=10, airtime=16, queue=2, retries=0.0, hop=1, sf=8, seen_ms=100)

        topo = TopologyManager(min_switch_interval_ms=0, hysteresis_margin=0.0)
        sf = SFController(n_up=1, n_down=3, cooldown_ms=0)
        cycle = LinkRouteController(topo, sf, mode="speed")

        before_1 = e1.current_sf
        before_2 = e2.current_sf

        result = cycle.run_cycle(table, now_ms=400)

        chosen = result["chosen_parent"]
        if result["sf_applied"]:
            if chosen == 1:
                self.assertNotEqual(e1.current_sf, before_1)
                self.assertEqual(e2.current_sf, before_2)
            elif chosen == 2:
                self.assertNotEqual(e2.current_sf, before_2)
                self.assertEqual(e1.current_sf, before_1)


if __name__ == "__main__":
    unittest.main()
