# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

import unittest

from app.controller import ControllerApp
from app.relay import RelayApp
from protocol.packets import PacketHeader, decode_packet, encode_typed_packet


class _Logger:
    def __init__(self):
        self.infos = []

    def info(self, *args, **kwargs):
        self.infos.append((args, kwargs))
        self.last_info = (args, kwargs)
        return None

    def warn(self, *args, **kwargs):
        return None


class _Runtime:
    def __init__(self, node_id):
        self.node_id = node_id


class _Radio:
    def __init__(self):
        self.sent = []
        self.spreading_factor = 9
        self.tx_mode = False
        self.rx_mode = False
        self._rssi = -78
        self._snr = 9

    def send_packet(self, pkt):
        self.sent.append(pkt)
        return True

    def set_tx_mode(self):
        self.tx_mode = True
        return True

    def set_rx_mode(self):
        self.rx_mode = True
        return True

    def get_rssi(self):
        return self._rssi

    def get_snr(self):
        return self._snr


class ControllerRelayTests(unittest.TestCase):
    def test_controller_queue_command_and_ack_complete(self):
        radio = _Radio()
        app = ControllerApp(radio, _Logger())
        app.setup(_Runtime(1))

        queued = app.queue_command("FORWARD", dst=2, requires_ack=True)
        self.assertTrue(queued)

        app.forwarder.process_tick(radio, now_ms=10**15)
        self.assertEqual(len(radio.sent), 1)

        # Build ACK from rover and ensure pending entry is cleared.
        ack_header = PacketHeader(src=2, dst=1, prev_hop=2, next_hop=1, seq=1, packet_type="ACK", ttl=1, sf=9)
        ack_raw = encode_typed_packet(ack_header, {"ack_seq": 1})
        app.on_packet(ack_raw)
        self.assertIsNone(app.forwarder.ack.get(1, 2))

    def test_controller_send_lora_transmits_immediately(self):
        radio = _Radio()
        app = ControllerApp(radio, _Logger())
        app.setup(_Runtime(1))

        app._handle_console_command("SEND_LORA:hello rover")

        self.assertEqual(radio.sent, [b"hello rover"])
        self.assertTrue(radio.tx_mode)
        self.assertTrue(radio.rx_mode)

    def test_controller_plain_text_transmits_immediately(self):
        radio = _Radio()
        app = ControllerApp(radio, _Logger())
        app.setup(_Runtime(1))

        app._handle_console_command("hello node2")

        self.assertEqual(radio.sent, [b"hello node2"])
        self.assertTrue(radio.tx_mode)
        self.assertTrue(radio.rx_mode)

    def test_controller_ble_name_includes_node_id(self):
        app = ControllerApp(_Radio(), _Logger())
        app.node_id = 7

        self.assertEqual(app._ble_device_name(), "LoRaLab_G13_N7")

    def test_controller_status_matches_fragmented_ble_input(self):
        radio = _Radio()
        logger = _Logger()
        app = ControllerApp(radio, logger)
        app.setup(_Runtime(1))

        app._handle_console_command("TATUSstatus")

        self.assertTrue(any("Controller status" in msg[0][0] for msg in logger.infos if msg and msg[0]))

    def test_controller_accepts_raw_lora_payload(self):
        radio = _Radio()
        logger = _Logger()
        app = ControllerApp(radio, logger)
        app.setup(_Runtime(1))

        app.on_packet(b"hello from node2")

        self.assertTrue(any("Controller RX RAW" in msg[0][0] for msg in logger.infos if msg and msg[0]))
        self.assertEqual(app.received_messages[-1]["text"], "hello from node2")

    def test_relay_forwards_once_and_suppresses_duplicate(self):
        relay_radio = _Radio()
        relay = RelayApp(relay_radio, _Logger())
        relay.setup(_Runtime(10))

        hdr = PacketHeader(src=1, dst=2, prev_hop=1, next_hop=10, seq=99, packet_type="DATA", ttl=4, sf=9)
        raw = encode_typed_packet(hdr, {"data": b"PING"})

        relay.on_packet(raw)
        relay.on_packet(raw)
        relay.forwarder.process_tick(relay_radio, now_ms=10**15)

        self.assertEqual(len(relay_radio.sent), 1)
        out_h, _ = decode_packet(relay_radio.sent[0])
        self.assertEqual(out_h.ttl, 3)


if __name__ == "__main__":
    unittest.main()
