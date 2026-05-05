# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Telemetry helpers for compact LoRa transport and serial debug output."""

import struct


_SNAPSHOT_FMT = "<HhbbHBBH"


def _clamp_u16(value):
    value = int(value)
    if value < 0:
        return 0
    if value > 0xFFFF:
        return 0xFFFF
    return value


def _clamp_i16(value):
    value = int(value)
    if value < -32768:
        return -32768
    if value > 32767:
        return 32767
    return value


def _clamp_i8(value):
    value = int(value)
    if value < -128:
        return -128
    if value > 127:
        return 127
    return value


def _clamp_u8(value):
    value = int(value)
    if value < 0:
        return 0
    if value > 255:
        return 255
    return value


def _as_float(value, fallback=0.0):
    if value is None:
        return float(fallback)
    return float(value)


def build_telemetry_snapshot(node_id=0, parent_id=0, hop_count=0, radio=None, link=None, battery_voltage=0.0, sensors=None):
    """Build telemetry dict used for binary transport and serial logs."""
    rssi = None
    snr = None
    current_sf = None
    retry_rate = 0.0
    pdr = 0.0

    if radio is not None:
        try:
            rssi = radio.get_rssi()
        except Exception:
            rssi = None
        try:
            snr = radio.get_snr()
        except Exception:
            snr = None

    if link is not None:
        current_sf = getattr(link, "current_sf", current_sf)
        parent_id = getattr(link, "parent_id", parent_id)
        hop_count = getattr(link, "hop_level", hop_count)
        retry_rate = _as_float(getattr(link, "retry_rate", retry_rate), retry_rate)
        pdr = _as_float(getattr(link, "pdr", pdr), pdr)
        if rssi is None:
            rssi = getattr(link, "avg_rssi_dbm", rssi)
        if snr is None:
            snr = getattr(link, "avg_snr_db", snr)

    if current_sf is None:
        current_sf = 0
    if rssi is None:
        rssi = 0
    if snr is None:
        snr = 0
    if sensors is None:
        sensors = {}

    return {
        "node_id": int(node_id),
        "battery_mv": int(round(_as_float(battery_voltage, 0.0) * 1000.0)),
        "rssi_dbm": int(round(_as_float(rssi, 0.0))),
        "snr_db": int(round(_as_float(snr, 0.0))),
        "current_sf": int(current_sf),
        "parent_id": int(parent_id),
        "hop_count": int(hop_count),
        "retry_rate_perc": int(round(max(0.0, retry_rate) * 100.0)),
        "pdr_perc": int(round(max(0.0, min(1.0, pdr)) * 100.0)),
        "sensors": dict(sensors),
    }


def encode_telemetry_binary(snapshot):
    """Encode compact telemetry payload suitable for LoRa transport.

    Packed fields:
    - node_id:u16
    - rssi_dbm:i16
    - snr_db:i8
    - current_sf:u8
    - parent_id:u16
    - hop_count:u8
    - retry_rate_perc:u8
    - battery_mv:u16
    """
    return struct.pack(
        _SNAPSHOT_FMT,
        _clamp_u16(snapshot.get("node_id", 0)),
        _clamp_i16(snapshot.get("rssi_dbm", 0)),
        _clamp_i8(snapshot.get("snr_db", 0)),
        _clamp_u8(snapshot.get("current_sf", 0)),
        _clamp_u16(snapshot.get("parent_id", 0)),
        _clamp_u8(snapshot.get("hop_count", 0)),
        _clamp_u8(snapshot.get("retry_rate_perc", 0)),
        _clamp_u16(snapshot.get("battery_mv", 0)),
    )


def decode_telemetry_binary(payload):
    values = struct.unpack(_SNAPSHOT_FMT, payload)
    return {
        "node_id": int(values[0]),
        "rssi_dbm": int(values[1]),
        "snr_db": int(values[2]),
        "current_sf": int(values[3]),
        "parent_id": int(values[4]),
        "hop_count": int(values[5]),
        "retry_rate_perc": int(values[6]),
        "battery_mv": int(values[7]),
    }


def format_telemetry_debug(snapshot):
    """Create readable serial/debug line for operators."""
    parts = [
        "id={0}".format(snapshot.get("node_id", 0)),
        "parent={0}".format(snapshot.get("parent_id", 0)),
        "hop={0}".format(snapshot.get("hop_count", 0)),
        "sf={0}".format(snapshot.get("current_sf", 0)),
        "rssi={0}dBm".format(snapshot.get("rssi_dbm", 0)),
        "snr={0}dB".format(snapshot.get("snr_db", 0)),
        "retry={0}%".format(snapshot.get("retry_rate_perc", 0)),
        "pdr={0}%".format(snapshot.get("pdr_perc", 0)),
        "bat={0}mV".format(snapshot.get("battery_mv", 0)),
    ]

    sensors = snapshot.get("sensors", {})
    if sensors:
        sensor_parts = []
        for key in sorted(sensors.keys()):
            sensor_parts.append("{0}={1}".format(key, sensors[key]))
        parts.append("sensors[" + ",".join(sensor_parts) + "]")

    return " ".join(parts)
