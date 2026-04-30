# SPDX-FileCopyrightText: 2026 Student Lab - COMP 4531 - HKUST
# SPDX-License-Identifier: MIT
#
# LoRa Mesh Echo Node — XIAO ESP32-S3 + SX1262  (simple M: flood protocol)
#
# Optimisations vs naive flood:
#   • Listen-Before-Talk  — 25 ms passive listen before every TX; exponential
#     backoff if busy; packets heard during LBT buffered, not dropped.
#   • RSSI-weighted relay  — strong signal → many neighbours already heard it
#     → lower relay probability.  Weak signal → relay almost always.
#   • Probabilistic relay  — never relay 100 % of the time; reduces airtime
#     by ~25 % with negligible packet-loss increase.
#   • Echo dedup  — won't echo the same (src, payload) twice within a window.
#   • Smart beacon  — skips beacon cycle if we transmitted recently.
#   • Larger dedup cache  (64 entries).
#   • Random beacon phase  — spread boot-time beacons across nodes.

import time
import random
import busio
import digitalio
import microcontroller
import board
import supervisor
import sys
from sx1262 import SX1262

# ── Identity ──────────────────────────────────────────────────────────────────
NODE_ID = 6     # unique per board (1–254); 1 = nRF gateway

# ── LoRa parameters ───────────────────────────────────────────────────────────
MESH_FREQ   = 912.0
BW          = 125.0
SF          = 7
CR          = 5
TTL_DEFAULT = 5

# ── Special dst values ────────────────────────────────────────────────────────
DST_BROADCAST = 0    # flood to all, standard relay rules apply
DST_LOCAL     = 255  # deliver everywhere, never relay (debug / echo-all)

# ── Tuning ────────────────────────────────────────────────────────────────────
CACHE_SIZE       = 64     # seen-message dedup entries
ECHO_CACHE_SIZE  = 16     # recent (src, payload) echoes to suppress duplicates
BEACON_INTERVAL  = 15.0   # seconds between beacons
LBT_LISTEN_MS    = 25     # passive listen window before TX (ms)
LBT_MAX_TRIES    = 5      # max LBT attempts before dropping packet
LBT_BASE_BACKOFF = 0.06   # base backoff (s); doubles each try + random jitter

# ── State ─────────────────────────────────────────────────────────────────────
seen_msgs   = []   # (src, mid) dedup cache
echo_cache  = []   # (src, payload) echo dedup cache
my_msg_id   = 0
relay_count = 0
_last_tx    = 0.0  # monotonic time of last successful TX
_pending    = None # packet buffered during LBT listen
_serial_buf = ''

# ── Pins ──────────────────────────────────────────────────────────────────────
sck_pin   = board.D8
miso_pin  = board.D9
mosi_pin  = board.D10
rst_pin   = board.D1
nss_pin   = microcontroller.pin.GPIO41
busy_pin  = microcontroller.pin.GPIO40
dio1_pin  = microcontroller.pin.GPIO39
rf_sw_pin = microcontroller.pin.GPIO38

# ── Hardware init ─────────────────────────────────────────────────────────────
try:
    rf_sw = digitalio.DigitalInOut(rf_sw_pin)
    rf_sw.direction = digitalio.Direction.OUTPUT
    rf_sw.value = False
    spi  = busio.SPI(sck_pin, mosi_pin, miso_pin)
    lora = SX1262(spi, sck_pin, mosi_pin, miso_pin,
                  nss_pin, dio1_pin, rst_pin, busy_pin)
    lora.begin(freq=MESH_FREQ, bw=BW, sf=SF, cr=CR,
               useRegulatorLDO=True, tcxoVoltage=1.8, power=22)
    print("Echo Node {}  {} MHz  SF{}  TTL={}".format(NODE_ID, MESH_FREQ, SF, TTL_DEFAULT))
except Exception as e:
    print("LoRa FAIL: {}".format(e))
    raise

# ── Dedup helpers ─────────────────────────────────────────────────────────────
def already_seen(src, mid):
    return (src, mid) in seen_msgs

def mark_seen(src, mid):
    seen_msgs.append((src, mid))
    if len(seen_msgs) > CACHE_SIZE:
        seen_msgs.pop(0)

def already_echoed(src, payload):
    return (src, payload) in echo_cache

def mark_echoed(src, payload):
    echo_cache.append((src, payload))
    if len(echo_cache) > ECHO_CACHE_SIZE:
        echo_cache.pop(0)

# ── Packet codec ──────────────────────────────────────────────────────────────
def encode_pkt(src, dst, mid, ttl, payload):
    return "M:{}:{}:{}:{}:{}".format(src, dst, mid, ttl, payload).encode()

def decode_pkt(raw):
    try:
        s = raw.decode().strip()
        if not s.startswith("M:"):
            return None
        parts = s[2:].split(":", 4)
        if len(parts) < 5:
            return None
        return int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]), parts[4]
    except Exception:
        return None

# ── RSSI-weighted relay probability ──────────────────────────────────────────
def _relay_prob(rssi):
    """Strong RSSI → many neighbours heard it → lower relay chance."""
    if rssi > -60:  return 0.40   # very strong — skip 60 % of relays
    if rssi > -75:  return 0.65   # medium
    if rssi > -90:  return 0.85   # weak but audible
    return 0.97                    # barely audible — almost always relay

# ── Listen-Before-Talk TX ─────────────────────────────────────────────────────
def lora_send_lbt(pkt_bytes):
    """Passive-listen channel check before TX.  Packets heard during checks
    are stored in _pending so the main loop can process them."""
    global _pending, _last_tx
    for attempt in range(LBT_MAX_TRIES):
        result = lora.recv(timeout_en=True, timeout_ms=LBT_LISTEN_MS)
        if result and isinstance(result, tuple) and len(result) >= 2 and result[0]:
            # Channel busy — buffer the received packet and back off
            if _pending is None:
                _pending = result
            backoff = LBT_BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 0.04)
            time.sleep(backoff)
            continue
        # Channel clear — transmit
        rf_sw.value = True
        lora.send(pkt_bytes)
        rf_sw.value = False
        _last_tx = time.monotonic()
        return True
    print("  LBT: tx dropped after {} tries".format(LBT_MAX_TRIES))
    return False

# ── Send originating packet ───────────────────────────────────────────────────
def mesh_send(payload, dst=DST_BROADCAST):
    global my_msg_id
    my_msg_id = (my_msg_id + 1) % 256
    mark_seen(NODE_ID, my_msg_id)
    pkt = encode_pkt(NODE_ID, dst, my_msg_id, TTL_DEFAULT, payload)
    if lora_send_lbt(pkt):
        print("TX src={} dst={} mid={} '{}'".format(NODE_ID, dst, my_msg_id, payload))

# ── Echo reply ────────────────────────────────────────────────────────────────
def echo_to_source(src, payload):
    if src == NODE_ID or src == 0:
        return
    if payload.startswith("ECHO:"):
        return
    if already_echoed(src, payload):
        return
    mark_echoed(src, payload)
    time.sleep(0.15 * NODE_ID)   # 150 ms * NODE_ID — ordered, collision-free
    mesh_send("ECHO:{}".format(payload), dst=src)
    print("  -> echo N{} '{}'".format(src, payload))

# ── Process one decoded packet ────────────────────────────────────────────────
def process_pkt(data):
    global relay_count
    pkt = decode_pkt(data)
    if not pkt:
        return
    src, dst, mid, ttl, payload = pkt
    rssi = lora.getRSSI()
    snr  = lora.getSNR()

    if already_seen(src, mid):
        return
    mark_seen(src, mid)
    print("RX src={} dst={} mid={} ttl={} rssi={} snr={:.1f} '{}'".format(
        src, dst, mid, ttl, rssi, snr, payload))

    # ── Deliver ───────────────────────────────────────────────────────────────
    if dst == NODE_ID or dst == DST_LOCAL:
        echo_to_source(src, payload)
    elif dst == DST_BROADCAST:
        if payload == "DISC":
            time.sleep(random.uniform(0.05, 0.20))
            mesh_send("BCN:{}".format(NODE_ID))
        elif payload.startswith("PARROT:"):
            time.sleep(random.uniform(0.05, 0.20))
            mesh_send("PONG:{}:{}".format(NODE_ID, payload[7:]), dst=src)
        else:
            echo_to_source(src, payload)

    # ── Relay ─────────────────────────────────────────────────────────────────
    # Skip: consumed unicast, DST_LOCAL, TTL exhausted, or probabilistic drop.
    if dst == NODE_ID or dst == DST_LOCAL or ttl <= 1:
        return
    if random.random() > _relay_prob(rssi):
        print("  -> relay skipped (prob, rssi={})".format(rssi))
        return
    relay_count += 1
    # Backoff: random window scaled to SF7 airtime (41 ms)
    time.sleep(random.uniform(0.05, 0.20))
    lora_send_lbt(encode_pkt(src, dst, mid, ttl - 1, payload))
    print("  -> relayed #{} ttl={}".format(relay_count, ttl - 1))

# ── Main loop ─────────────────────────────────────────────────────────────────
print("Echo node {} running".format(NODE_ID))
last_beacon = time.monotonic() - random.uniform(0, BEACON_INTERVAL * 0.9)

while True:
    # Serial input
    try:
        if supervisor.runtime.serial_bytes_available:
            chunk = sys.stdin.read(supervisor.runtime.serial_bytes_available)
            _serial_buf += chunk
            while '\n' in _serial_buf or '\r' in _serial_buf:
                for sep in ('\n', '\r'):
                    if sep in _serial_buf:
                        line, _serial_buf = _serial_buf.split(sep, 1)
                        break
                text = line.strip()
                if text:
                    if text.startswith("TO:"):
                        parts = text[3:].split(":", 1)
                        if len(parts) == 2:
                            mesh_send(parts[1], dst=int(parts[0]))
                        else:
                            print("Usage: TO:<dst>:<msg>")
                    else:
                        mesh_send(text)
    except Exception as e:
        print("Serial err: {}".format(e))

    # Drain pending packet buffered during LBT
    if _pending is not None:
        data, _ = _pending
        _pending = None
        if data:
            try:
                process_pkt(data)
            except Exception as e:
                print("Pending pkt err: {}".format(e))

    # Normal RX
    try:
        result = lora.recv(timeout_en=True, timeout_ms=300)
        if result and isinstance(result, tuple) and len(result) >= 2 and result[0]:
            process_pkt(result[0])
    except Exception as e:
        print("RX err: {}".format(e))

    # Beacon — skip if transmitted recently (channel likely active)
    now = time.monotonic()
    if now - last_beacon >= BEACON_INTERVAL:
        last_beacon = now
        if now - _last_tx > 1.0:   # 1 s quiet guard
            mesh_send("BCN:{}".format(NODE_ID))
        else:
            print("Beacon skipped (recent TX)")

    time.sleep(0.005)
