# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

import unittest

from boards import board_generic
from radio.backends.sx1262_micropython import SX1262MicroPythonBackend


class MicroPythonBackendTests(unittest.TestCase):
    def test_initialize_fails_gracefully_without_machine(self):
        backend = SX1262MicroPythonBackend(board_generic, {"frequency_hz": 923000000})
        ok = backend.initialize()
        self.assertFalse(ok)
        self.assertIsNotNone(backend.last_error)
        self.assertFalse(backend.initialized)


if __name__ == "__main__":
    unittest.main()
