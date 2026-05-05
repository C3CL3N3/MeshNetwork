# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

import unittest

import config
from radio.lora_iface import LoRaInterface
from radio.backends.sx1262_circuitpython import SX1262CircuitPythonBackend
from radio.radio_config import normalize_board_profile


class RadioInterfaceTests(unittest.TestCase):
    def test_board_profile_selection(self):
        radio = LoRaInterface(board_profile="esp32s3_sx1262", backend_name="stub")
        self.assertEqual(radio.board_module.BOARD_NAME, "esp32s3_sx1262")

    def test_default_board_profile_uses_config_value(self):
        radio = LoRaInterface(backend_name="stub")
        expected = normalize_board_profile(config.BOARD_PROFILE)
        self.assertEqual(radio.board_module.BOARD_NAME, expected)

    def test_board_profile_alias_is_normalized(self):
        radio = LoRaInterface(board_profile="esp32s3-sx1262", backend_name="stub")
        self.assertEqual(radio.board_module.BOARD_NAME, "esp32s3_sx1262")

    def test_runtime_setters_sync_to_backend(self):
        radio = LoRaInterface(board_profile="nrf52840_sx1262", backend_name="stub")
        radio.initialize()
        radio.set_frequency(923100000)
        radio.set_bandwidth(250000)
        radio.set_coding_rate(6)
        radio.set_spreading_factor(8)

        self.assertEqual(radio.frequency_hz, 923100000)
        self.assertEqual(radio.backend.settings["frequency_hz"], 923100000)
        self.assertEqual(radio.backend.settings["bandwidth_hz"], 250000)
        self.assertEqual(radio.backend.settings["coding_rate"], 6)
        self.assertEqual(radio.backend.settings["spreading_factor"], 8)

    def test_prompt_alias_methods(self):
        radio = LoRaInterface(backend_name="stub")
        radio.setFrequency(923200000)
        radio.setBandwidth(125000)
        radio.setCodingRate(5)
        radio.setSpreadingFactor(9)
        self.assertEqual(radio.frequency_hz, 923200000)
        self.assertTrue(radio.sendPacket(b"hi"))
        self.assertIsNone(radio.receivePacket(timeout_ms=1))

    def test_circuitpython_backend_selected(self):
        radio = LoRaInterface(backend_name="circuitpython")
        self.assertEqual(radio.backend_name, "circuitpython")
        self.assertIsInstance(radio.backend, SX1262CircuitPythonBackend)

    def test_diagnostics_contains_expected_fields(self):
        radio = LoRaInterface(backend_name="stub", board_profile="generic")
        radio.initialize()
        diag = radio.diagnostics()

        self.assertEqual(diag["backend"], "stub")
        self.assertEqual(diag["board_profile"], "generic")
        self.assertTrue(diag["initialized"])
        self.assertIn("has_spi", diag)
        self.assertIn("has_driver", diag)
        self.assertIn("last_error", diag)


if __name__ == "__main__":
    unittest.main()
