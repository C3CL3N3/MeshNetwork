# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

import unittest

from tools.sim_harness import run_simulation


class SimHarnessTests(unittest.TestCase):
    def test_harness_runs_and_logs_core_decisions(self):
        result = run_simulation(node_count=4)
        log = "\n".join(result["log"])

        self.assertIn("speed_mode", log)
        self.assertIn("throughput_mode", log)
        self.assertIn("sf_actions", log)
        self.assertIn("duplicate_check", log)
        self.assertIn("failover", log)

    def test_summary_flags_expected(self):
        result = run_simulation(node_count=4)
        summary = result["summary"]

        self.assertTrue(summary["duplicate_suppressed"])
        self.assertTrue(summary["rejoin_required"])
        self.assertGreaterEqual(summary["sf_after"], 9)

    def test_invalid_node_count_rejected(self):
        with self.assertRaises(ValueError):
            run_simulation(node_count=2)
        with self.assertRaises(ValueError):
            run_simulation(node_count=6)


if __name__ == "__main__":
    unittest.main()
