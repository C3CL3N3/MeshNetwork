# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

import unittest

from app.rover import RoverApp
from protocol.packets import PacketHeader, encode_typed_packet


class _FakeLogger:
    def info(self, *args, **kwargs):
        return None

    def warn(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


class _Runtime:
    node_id = 2


class _FakeRadio:
    def receive_packet(self, timeout_ms=0):
        _ = timeout_ms
        return None


class _Motor:
    def __init__(self):
        self.left = 0
        self.right = 0
        self.stopped = True

    def stop(self):
        self.left = 0
        self.right = 0
        self.stopped = True
        return True

    def set_motion(self, left, right):
        self.left = int(left)
        self.right = int(right)
        self.stopped = self.left == 0 and self.right == 0
        return True


def _make_data_packet(src, dst, seq, command_text, ttl=4, sf=9):
    h = PacketHeader(src=src, dst=dst, prev_hop=src, next_hop=dst, seq=seq, packet_type="DATA", ttl=ttl, sf=sf)
    return encode_typed_packet(h, {"data": command_text.encode("utf-8")})


class RoverAppTests(unittest.TestCase):
    def _app(self):
        motor = _Motor()
        app = RoverApp(_FakeRadio(), _FakeLogger(), motor_driver=motor)
        app.setup(_Runtime())
        return app, motor

    def test_forward_and_stop_commands(self):
        app, motor = self._app()
        app.on_packet(_make_data_packet(src=1, dst=2, seq=1, command_text="FORWARD"))
        self.assertFalse(motor.stopped)
        self.assertGreater(motor.left, 0)
        self.assertGreater(motor.right, 0)

        app.on_packet(_make_data_packet(src=1, dst=2, seq=2, command_text="STOP"))
        self.assertTrue(motor.stopped)

    def test_set_speed_and_turn_right(self):
        app, motor = self._app()
        app.on_packet(_make_data_packet(src=1, dst=2, seq=1, command_text="SET_SPEED 200"))
        app.on_packet(_make_data_packet(src=1, dst=2, seq=2, command_text="TURN_RIGHT"))
        self.assertGreater(motor.left, 0)
        self.assertLess(motor.right, 0)

    def test_duplicate_sequence_ignored(self):
        app, motor = self._app()
        app.on_packet(_make_data_packet(src=1, dst=2, seq=10, command_text="FORWARD"))
        left_1, right_1 = motor.left, motor.right

        app.on_packet(_make_data_packet(src=1, dst=2, seq=10, command_text="BACKWARD"))
        self.assertEqual(motor.left, left_1)
        self.assertEqual(motor.right, right_1)

    def test_watchdog_stops_motion(self):
        app, motor = self._app()
        app.on_packet(_make_data_packet(src=1, dst=2, seq=1, command_text="FORWARD"))
        self.assertFalse(motor.stopped)

        # Force watchdog age-out by adjusting last command timestamp.
        app.last_valid_cmd_ms = 1
        app.tick()
        self.assertTrue(motor.stopped)

    def test_invalid_destination_ignored(self):
        app, motor = self._app()
        app.on_packet(_make_data_packet(src=1, dst=9, seq=1, command_text="FORWARD"))
        self.assertTrue(motor.stopped)


if __name__ == "__main__":
    unittest.main()
