# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Compact packet format for LoRa mesh transport.

Wire format:
| src:u16 | dst:u16 | prev_hop:u16 | next_hop:u16 | seq:u16 |
| type:u8 | ttl:u8 | flags:u8 | sf:u8 | payload_len:u8 | payload | crc16:u16 |
"""

import struct

from config import DEFAULT_PACKET_TTL, LORA_DEFAULT_SF, LORA_MAX_SF, LORA_MIN_SF, MAX_PACKET_PAYLOAD
from protocol.crc import crc16_ccitt_false


PACKET_TYPES = (
    "HELLO",
    "BEACON",
    "METRIC",
    "DATA",
    "ACK",
    "SF_HINT",
    "JOIN",
    "REJOIN",
)
PACKET_TYPE_TO_ID = {name: idx for idx, name in enumerate(PACKET_TYPES)}
PACKET_ID_TO_TYPE = {idx: name for idx, name in enumerate(PACKET_TYPES)}

PAYLOAD_SCHEMAS = {
    # role:u8, battery_tenths:u16, caps:u16
    "HELLO": ("<BHH", ("role", "battery_tenths", "caps")),
    # beacon_id:u16, network_time_ms:u32
    "BEACON": ("<HI", ("beacon_id", "network_time_ms")),
    # avg_rssi_dbm:i8, avg_snr_db:i8, pdr_percent:u8, retry_percent:u8, parent_id:u16, child_count:u8, current_sf:u8
    "METRIC": ("<bbBBHBB", ("avg_rssi_dbm", "avg_snr_db", "pdr_percent", "retry_percent", "parent_id", "child_count", "current_sf")),
    # ack_seq:u16
    "ACK": ("<H", ("ack_seq",)),
    # suggested_sf:u8, reason:u8
    "SF_HINT": ("<BB", ("suggested_sf", "reason")),
    # requested_role:u8
    "JOIN": ("<B", ("requested_role",)),
    # reason:u8, requested_parent:u16
    "REJOIN": ("<BH", ("reason", "requested_parent")),
}

_HEADER_FMT = "<HHHHHBBBBB"
HEADER_SIZE = struct.calcsize(_HEADER_FMT)
CRC_SIZE = 2
MIN_PACKET_SIZE = HEADER_SIZE + CRC_SIZE
MAX_PACKET_SIZE = HEADER_SIZE + MAX_PACKET_PAYLOAD + CRC_SIZE


class PacketError(ValueError):
    """Raised when a packet fails to encode/decode validation."""


class PacketHeader:
    __slots__ = (
        "src",
        "dst",
        "prev_hop",
        "next_hop",
        "seq",
        "type",
        "ttl",
        "flags",
        "sf",
    )

    def __init__(
        self,
        src=0,
        dst=0,
        prev_hop=0,
        next_hop=0,
        seq=0,
        packet_type=0,
        ttl=DEFAULT_PACKET_TTL,
        flags=0,
        sf=LORA_DEFAULT_SF,
    ):
        self.src = src
        self.dst = dst
        self.prev_hop = prev_hop
        self.next_hop = next_hop
        self.seq = seq
        self.type = packet_type
        self.ttl = ttl
        self.flags = flags
        self.sf = sf


def _u16(value, field_name):
    if not isinstance(value, int) or value < 0 or value > 0xFFFF:
        raise PacketError("{0} must be 0..65535".format(field_name))
    return value


def _u8(value, field_name):
    if not isinstance(value, int) or value < 0 or value > 0xFF:
        raise PacketError("{0} must be 0..255".format(field_name))
    return value


def _normalize_packet_type(packet_type):
    if isinstance(packet_type, str):
        key = packet_type.upper()
        if key not in PACKET_TYPE_TO_ID:
            raise PacketError("unknown packet type: {0}".format(packet_type))
        return PACKET_TYPE_TO_ID[key]
    if isinstance(packet_type, int) and packet_type in PACKET_ID_TO_TYPE:
        return packet_type
    raise PacketError("unknown packet type: {0}".format(packet_type))


def _normalize_payload(payload):
    if payload is None:
        payload = b""
    if isinstance(payload, memoryview):
        payload = payload.tobytes()
    elif isinstance(payload, bytearray):
        payload = bytes(payload)
    elif not isinstance(payload, bytes):
        raise PacketError("payload must be bytes-like")

    if len(payload) > MAX_PACKET_PAYLOAD:
        raise PacketError("payload exceeds MAX_PACKET_PAYLOAD")
    return payload


def encode_packet(header, payload=b""):
    """Encode header and payload into compact binary packet with CRC16."""
    if not isinstance(header, PacketHeader):
        raise PacketError("header must be PacketHeader")

    packet_type = _normalize_packet_type(header.type)
    payload = _normalize_payload(payload)

    if header.sf < LORA_MIN_SF or header.sf > LORA_MAX_SF:
        raise PacketError("sf out of configured range")

    header_bytes = struct.pack(
        _HEADER_FMT,
        _u16(header.src, "src"),
        _u16(header.dst, "dst"),
        _u16(header.prev_hop, "prev_hop"),
        _u16(header.next_hop, "next_hop"),
        _u16(header.seq, "seq"),
        _u8(packet_type, "type"),
        _u8(header.ttl, "ttl"),
        _u8(header.flags, "flags"),
        _u8(header.sf, "sf"),
        _u8(len(payload), "payload_len"),
    )

    body = header_bytes + payload
    crc = crc16_ccitt_false(body)
    return body + struct.pack("<H", crc)


def decode_packet(raw):
    """Decode and validate a packet.

    Returns: (PacketHeader, payload_bytes)
    """
    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    elif isinstance(raw, bytearray):
        raw = bytes(raw)
    elif not isinstance(raw, bytes):
        raise PacketError("raw packet must be bytes-like")

    size = len(raw)
    if size < MIN_PACKET_SIZE:
        raise PacketError("packet too small")
    if size > MAX_PACKET_SIZE:
        raise PacketError("packet too large")

    content = raw[:-CRC_SIZE]
    recv_crc = struct.unpack("<H", raw[-CRC_SIZE:])[0]
    calc_crc = crc16_ccitt_false(content)
    if recv_crc != calc_crc:
        raise PacketError("crc mismatch")

    unpacked = struct.unpack(_HEADER_FMT, content[:HEADER_SIZE])
    payload_len = unpacked[9]
    payload = content[HEADER_SIZE:]
    if payload_len != len(payload):
        raise PacketError("payload length mismatch")

    header = PacketHeader(
        src=unpacked[0],
        dst=unpacked[1],
        prev_hop=unpacked[2],
        next_hop=unpacked[3],
        seq=unpacked[4],
        packet_type=unpacked[5],
        ttl=unpacked[6],
        flags=unpacked[7],
        sf=unpacked[8],
    )
    if header.type not in PACKET_ID_TO_TYPE:
        raise PacketError("unknown type id")
    if header.sf < LORA_MIN_SF or header.sf > LORA_MAX_SF:
        raise PacketError("sf out of configured range")

    return header, payload


def packet_type_name(type_id):
    return PACKET_ID_TO_TYPE.get(type_id, "UNKNOWN")


def encode_typed_payload(packet_type, fields):
    """Encode typed payload fields for a known packet type.

    DATA payloads are raw bytes (or provided as {"data": bytes}).
    """
    type_id = _normalize_packet_type(packet_type)
    type_name = PACKET_ID_TO_TYPE[type_id]

    if type_name == "DATA":
        if isinstance(fields, dict):
            return _normalize_payload(fields.get("data", b""))
        return _normalize_payload(fields)

    schema = PAYLOAD_SCHEMAS.get(type_name)
    if schema is None:
        return b""

    if not isinstance(fields, dict):
        raise PacketError("typed payload fields must be a dict")

    fmt, keys = schema
    values = []
    for key in keys:
        if key not in fields:
            raise PacketError("missing payload field: {0}".format(key))
        values.append(fields[key])

    try:
        payload = struct.pack(fmt, *values)
    except struct.error as exc:
        raise PacketError("payload encoding failed: {0}".format(exc))
    return _normalize_payload(payload)


def decode_typed_payload(packet_type, payload):
    """Decode typed payload bytes into a dictionary."""
    type_id = _normalize_packet_type(packet_type)
    type_name = PACKET_ID_TO_TYPE[type_id]
    payload = _normalize_payload(payload)

    if type_name == "DATA":
        return {"data": payload}

    schema = PAYLOAD_SCHEMAS.get(type_name)
    if schema is None:
        return {"raw": payload}

    fmt, keys = schema
    expected = struct.calcsize(fmt)
    if len(payload) != expected:
        raise PacketError("payload size mismatch for {0}".format(type_name))

    values = struct.unpack(fmt, payload)
    result = {}
    for idx, key in enumerate(keys):
        result[key] = values[idx]
    return result


def encode_typed_packet(header, fields):
    """Encode a full packet using typed payload fields based on header.type."""
    payload = encode_typed_payload(header.type, fields)
    return encode_packet(header, payload)


def decode_typed_packet(raw):
    """Decode packet and return (header, typed_payload_dict)."""
    header, payload = decode_packet(raw)
    typed = decode_typed_payload(header.type, payload)
    return header, typed
