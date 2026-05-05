# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Generic LoRa radio interface with pluggable SX1262 backends."""

from config import RADIO_BACKEND
from radio.backends.sx1262_circuitpython import SX1262CircuitPythonBackend
from radio.backends.sx1262_micropython import SX1262MicroPythonBackend
from radio.backends.sx1262_stub import SX1262StubBackend
from radio.radio_config import load_board_module, radio_runtime_settings


class LoRaInterface:
    def __init__(self, board_profile=None, backend_name=None, **settings_overrides):
        self.board_module = load_board_module(board_profile)
        self.settings = radio_runtime_settings(**settings_overrides)

        self.frequency_hz = self.settings["frequency_hz"]
        self.bandwidth_hz = self.settings["bandwidth_hz"]
        self.coding_rate = self.settings["coding_rate"]
        self.spreading_factor = self.settings["spreading_factor"]

        selected_backend = backend_name or RADIO_BACKEND
        self.backend_name = selected_backend
        self.backend = _make_backend(selected_backend, self.board_module, self.settings)

    def initialize(self):
        return self.backend.initialize()

    def diagnostics(self):
        board_name = getattr(self.board_module, "BOARD_NAME", "unknown")
        last_error = getattr(self.backend, "last_error", None)
        has_driver = getattr(self.backend, "_driver", None) is not None
        has_spi = getattr(self.backend, "spi", None) is not None
        return {
            "backend": self.backend_name,
            "board_profile": board_name,
            "initialized": bool(getattr(self.backend, "initialized", False)),
            "has_spi": has_spi,
            "has_driver": has_driver,
            "last_error": last_error,
            "frequency_hz": self.frequency_hz,
            "bandwidth_hz": self.bandwidth_hz,
            "coding_rate": self.coding_rate,
            "spreading_factor": self.spreading_factor,
        }

    def set_frequency(self, freq_hz):
        self.frequency_hz = int(freq_hz)
        self.backend.set_frequency(self.frequency_hz)

    def set_bandwidth(self, bandwidth_hz):
        self.bandwidth_hz = int(bandwidth_hz)
        self.backend.set_bandwidth(self.bandwidth_hz)

    def set_coding_rate(self, coding_rate):
        self.coding_rate = int(coding_rate)
        self.backend.set_coding_rate(self.coding_rate)

    def set_spreading_factor(self, sf):
        self.spreading_factor = int(sf)
        self.backend.set_spreading_factor(self.spreading_factor)

    def send_packet(self, data):
        return self.backend.send_packet(data)

    def receive_packet(self, timeout_ms=0):
        return self.backend.receive_packet(timeout_ms=timeout_ms)

    def get_rssi(self):
        return self.backend.get_rssi()

    def get_snr(self):
        return self.backend.get_snr()

    def cad(self):
        return self.backend.cad()

    def set_tx_mode(self):
        fn = getattr(self.backend, "set_tx_mode", None)
        if callable(fn):
            return fn()
        return False

    def set_rx_mode(self):
        fn = getattr(self.backend, "set_rx_mode", None)
        if callable(fn):
            return fn()
        return False

    # Prompt compatibility aliases requested in spec wording.
    def setFrequency(self, freq_hz):
        self.set_frequency(freq_hz)

    def setBandwidth(self, bandwidth_hz):
        self.set_bandwidth(bandwidth_hz)

    def setCodingRate(self, coding_rate):
        self.set_coding_rate(coding_rate)

    def setSpreadingFactor(self, sf):
        self.set_spreading_factor(sf)

    def sendPacket(self, data):
        return self.send_packet(data)

    def receivePacket(self, timeout_ms=0):
        return self.receive_packet(timeout_ms=timeout_ms)

    def getRSSI(self):
        return self.get_rssi()

    def getSNR(self):
        return self.get_snr()


def _make_backend(name, board_module, settings):
    if name == "micropython":
        return SX1262MicroPythonBackend(board_module, settings)
    if name == "circuitpython":
        return SX1262CircuitPythonBackend(board_module, settings)
    return SX1262StubBackend(board_module, settings)
