# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

import unittest

from config import LORA_DEFAULT_SF, MAX_PACKET_PAYLOAD
from protocol.packets import (
    PacketError,
    PacketHeader,
    decode_packet,
    decode_typed_packet,
    decode_typed_payload,
    encode_packet,
    encode_typed_packet,
    encode_typed_payload,
)


class ProtocolPacketTests(unittest.TestCase):
    def test_encode_decode_round_trip(self):
        header = PacketHeader(
            src=1,
            dst=2,
            prev_hop=1,
            next_hop=2,
            seq=17,
            packet_type="DATA",
            ttl=8,
            flags=0,
            sf=LORA_DEFAULT_SF,
        )
        payload = b"abc123"

        raw = encode_packet(header, payload)
        decoded_header, decoded_payload = decode_packet(raw)

        self.assertEqual(decoded_header.src, 1)
        self.assertEqual(decoded_header.dst, 2)
        self.assertEqual(decoded_header.seq, 17)
        self.assertEqual(decoded_header.type, 3)  # DATA
        self.assertEqual(decoded_payload, payload)

    def test_crc_failure_rejected(self):
        header = PacketHeader(src=10, dst=11, seq=1, packet_type="ACK", sf=LORA_DEFAULT_SF)
        raw = bytearray(encode_packet(header, b"ok"))
        raw[-1] ^= 0xFF

        with self.assertRaises(PacketError):
            decode_packet(bytes(raw))

    def test_payload_limit_enforced(self):
        header = PacketHeader(src=1, dst=2, seq=2, packet_type="DATA", sf=LORA_DEFAULT_SF)
        too_large = b"x" * (MAX_PACKET_PAYLOAD + 1)
        with self.assertRaises(PacketError):
            encode_packet(header, too_large)

    def test_typed_metric_round_trip(self):
        header = PacketHeader(src=20, dst=1, seq=10, packet_type="METRIC", sf=9)
        fields = {
            "avg_rssi_dbm": -78,
            "avg_snr_db": 7,
            "pdr_percent": 96,
            "retry_percent": 4,
            "parent_id": 1,
            "child_count": 2,
            "current_sf": 9,
        }
        raw = encode_typed_packet(header, fields)
        decoded_header, decoded_fields = decode_typed_packet(raw)

        self.assertEqual(decoded_header.type, 2)  # METRIC
        self.assertEqual(decoded_fields["avg_rssi_dbm"], -78)
        self.assertEqual(decoded_fields["parent_id"], 1)
        self.assertEqual(decoded_fields["current_sf"], 9)

    def test_typed_payload_missing_field_rejected(self):
        with self.assertRaises(PacketError):
            encode_typed_payload("ACK", {})

    def test_typed_payload_size_validation(self):
        with self.assertRaises(PacketError):
            decode_typed_payload("ACK", b"\x01")

    def test_data_typed_payload_passthrough(self):
        payload = encode_typed_payload("DATA", {"data": b"rover"})
        self.assertEqual(payload, b"rover")


if __name__ == "__main__":
    unittest.main()
