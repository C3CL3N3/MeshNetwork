# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

import unittest

from net.forwarder import Forwarder
from protocol.packets import PacketHeader, decode_packet, decode_typed_packet, encode_typed_packet


class _FakeRadio:
    def __init__(self):
        self.sent = []

    def send_packet(self, packet):
        self.sent.append(packet)
        return True


class ForwarderTests(unittest.TestCase):
    def test_ttl_expired_not_forwarded(self):
        fwd = Forwarder(node_id=2)
        header = PacketHeader(src=1, dst=9, prev_hop=1, next_hop=2, seq=10, packet_type="DATA", ttl=1, sf=9)
        payload = b"cmd"

        result = fwd.process_incoming(header, payload, now_ms=100)
        self.assertFalse(result["should_forward"])
        self.assertTrue(result["consumed"])

    def test_forward_decrements_ttl(self):
        fwd = Forwarder(node_id=2)
        radio = _FakeRadio()
        header = PacketHeader(src=1, dst=9, prev_hop=1, next_hop=2, seq=11, packet_type="DATA", ttl=3, sf=9)

        result = fwd.process_incoming(header, b"data", now_ms=100)
        self.assertTrue(result["should_forward"])
        self.assertEqual(result["forward_header"].ttl, 2)

        sent = fwd.process_tick(radio, now_ms=1000)
        self.assertEqual(sent, 1)
        decoded_h, decoded_payload = decode_packet(radio.sent[0])
        self.assertEqual(decoded_h.ttl, 2)
        self.assertEqual(decoded_payload, b"data")

    def test_duplicate_suppression(self):
        fwd = Forwarder(node_id=2)
        header = PacketHeader(src=1, dst=9, prev_hop=1, next_hop=2, seq=22, packet_type="DATA", ttl=4, sf=9)

        first = fwd.process_incoming(header, b"x", now_ms=100)
        second = fwd.process_incoming(header, b"x", now_ms=101)

        self.assertTrue(first["should_forward"])
        self.assertTrue(second["duplicate"])

    def test_ack_scheduled_for_local_delivery(self):
        fwd = Forwarder(node_id=2)
        radio = _FakeRadio()
        header = PacketHeader(src=1, dst=2, prev_hop=1, next_hop=2, seq=33, packet_type="DATA", ttl=4, sf=9)

        result = fwd.process_incoming(header, b"payload", now_ms=100)
        self.assertTrue(result["ack_scheduled"])

        fwd.process_tick(radio, now_ms=500)
        ack_header, ack_typed = decode_typed_packet(radio.sent[0])
        self.assertEqual(ack_header.dst, 1)
        self.assertEqual(ack_typed["ack_seq"], 33)

    def test_ack_retry_then_complete(self):
        fwd = Forwarder(node_id=2, max_retries=2, ack_timeout_ms=50)
        radio = _FakeRadio()

        outbound = PacketHeader(src=2, dst=7, prev_hop=2, next_hop=7, seq=44, packet_type="DATA", ttl=4, sf=9)
        queued = fwd.queue_outbound(outbound, payload_fields=b"abc", requires_ack=True, now_ms=100)
        self.assertTrue(queued)

        fwd.process_tick(radio, now_ms=200)
        self.assertEqual(len(radio.sent), 1)

        # Timeout triggers retry.
        fwd.process_tick(radio, now_ms=400)
        self.assertGreaterEqual(len(radio.sent), 2)

        # Receive ACK clears pending.
        ack_header = PacketHeader(src=7, dst=2, prev_hop=7, next_hop=2, seq=44, packet_type="ACK", ttl=1, sf=9)
        ack_packet = encode_typed_packet(ack_header, {"ack_seq": 44})
        decoded_ack_h, decoded_ack_payload = decode_packet(ack_packet)
        fwd.process_incoming(decoded_ack_h, decoded_ack_payload, now_ms=450)

        self.assertIsNone(fwd.ack.get(44, 7))


if __name__ == "__main__":
    unittest.main()
