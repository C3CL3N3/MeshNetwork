# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

import unittest

from app.telemetry import (
    build_telemetry_snapshot,
    decode_telemetry_binary,
    encode_telemetry_binary,
    format_telemetry_debug,
)


class _Radio:
    def __init__(self, rssi=-82, snr=7):
        self._rssi = rssi
        self._snr = snr

    def get_rssi(self):
        return self._rssi

    def get_snr(self):
        return self._snr


class _Link:
    current_sf = 9
    parent_id = 12
    hop_level = 2
    retry_rate = 0.15
    pdr = 0.93
    avg_rssi_dbm = -80
    avg_snr_db = 6


class TelemetryTests(unittest.TestCase):
    def test_snapshot_collects_core_fields(self):
        snap = build_telemetry_snapshot(
            node_id=7,
            radio=_Radio(-85, 5),
            link=_Link(),
            battery_voltage=3.74,
            sensors={"temp": 25.5},
        )

        self.assertEqual(snap["node_id"], 7)
        self.assertEqual(snap["parent_id"], 12)
        self.assertEqual(snap["hop_count"], 2)
        self.assertEqual(snap["current_sf"], 9)
        self.assertEqual(snap["rssi_dbm"], -85)
        self.assertEqual(snap["snr_db"], 5)
        self.assertEqual(snap["battery_mv"], 3740)
        self.assertEqual(snap["retry_rate_perc"], 15)
        self.assertEqual(snap["pdr_perc"], 93)

    def test_binary_round_trip(self):
        snap = {
            "node_id": 3,
            "rssi_dbm": -90,
            "snr_db": 4,
            "current_sf": 8,
            "parent_id": 1,
            "hop_count": 2,
            "retry_rate_perc": 10,
            "battery_mv": 3650,
        }
        payload = encode_telemetry_binary(snap)
        decoded = decode_telemetry_binary(payload)

        self.assertEqual(decoded["node_id"], 3)
        self.assertEqual(decoded["rssi_dbm"], -90)
        self.assertEqual(decoded["current_sf"], 8)
        self.assertEqual(decoded["battery_mv"], 3650)

    def test_debug_format_contains_expected_fields(self):
        snap = {
            "node_id": 2,
            "parent_id": 1,
            "hop_count": 1,
            "current_sf": 7,
            "rssi_dbm": -77,
            "snr_db": 9,
            "retry_rate_perc": 0,
            "pdr_perc": 99,
            "battery_mv": 3820,
            "sensors": {"imu": "ok", "temp": 24.2},
        }
        text = format_telemetry_debug(snap)
        self.assertIn("id=2", text)
        self.assertIn("sf=7", text)
        self.assertIn("bat=3820mV", text)
        self.assertIn("sensors[imu=ok,temp=24.2]", text)


if __name__ == "__main__":
    unittest.main()
