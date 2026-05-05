# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""CRC helpers for packet integrity checks."""


def crc16_ccitt_false(data, init=0xFFFF):
    """Compute CRC-16/CCITT-FALSE over bytes-like input."""
    crc = int(init) & 0xFFFF
    for byte in data:
        crc ^= (byte & 0xFF) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def crc16(data):
    """Compatibility alias used by earlier scaffold code."""
    return crc16_ccitt_false(data)
