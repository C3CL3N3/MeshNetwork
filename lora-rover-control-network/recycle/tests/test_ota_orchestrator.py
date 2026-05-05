# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

import unittest

from tools.ota_orchestrator import build_plan


class OtaOrchestratorTests(unittest.TestCase):
    def test_two_node_plan_shape(self):
        plan = build_plan("two-node", ["COM5", "COM8"], project_root=".")
        self.assertEqual(len(plan), 2)
        self.assertEqual(plan[0]["node"]["role"], "controller")
        self.assertEqual(plan[1]["node"]["role"], "rover")

    def test_insufficient_ports_rejected(self):
        with self.assertRaises(ValueError):
            build_plan("one-relay", ["COM5"], project_root=".")


if __name__ == "__main__":
    unittest.main()
