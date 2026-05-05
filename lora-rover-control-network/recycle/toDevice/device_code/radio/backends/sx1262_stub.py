# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""SX1262 backend stub used for Prompt 3 and host testing."""


class SX1262StubBackend:
    def __init__(self, board_module, settings):
        self.board = board_module
        self.settings = dict(settings)
        self.initialized = False
        self.last_rssi = None
        self.last_snr = None

    def initialize(self):
        self.initialized = True
        return True

    def set_frequency(self, freq_hz):
        self.settings["frequency_hz"] = int(freq_hz)

    def set_bandwidth(self, bandwidth_hz):
        self.settings["bandwidth_hz"] = int(bandwidth_hz)

    def set_coding_rate(self, coding_rate):
        self.settings["coding_rate"] = int(coding_rate)

    def set_spreading_factor(self, sf):
        self.settings["spreading_factor"] = int(sf)

    def send_packet(self, data):
        _ = data
        return True

    def receive_packet(self, timeout_ms=0):
        _ = timeout_ms
        return None

    def get_rssi(self):
        return self.last_rssi

    def get_snr(self):
        return self.last_snr

    def cad(self):
        return False
