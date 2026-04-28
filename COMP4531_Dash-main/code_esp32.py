# SPDX-FileCopyrightText: 2026 Student Lab - COMP 4531 - HKUST
# SPDX-License-Identifier: MIT
#
# LoRa Mesh Relay Node — XIAO ESP32-S3 + SX1262
# Floods received packets (TTL decrement + dedup).
# Originates a beacon every 30 s so other nodes know it exists.

import time
import busio
import digitalio
import microcontroller
import board
import supervisor
import sys
from sx1262 import SX1262

# ── Identity ──────────────────────────────────────────────────────────────────
NODE_ID   = 2     # ← unique per physical board within the mesh (e.g. 1, 2, 3…)

# ── LoRa Parameters ───────────────────────────────────────────────────────────
# MESH_FREQ must be identical on every node in the network.
MESH_FREQ   = 912.0   # MHz — must match code_nrf.py exactly
BW          = 125.0
SF          = 7       # Must match all other mesh nodes
CR          = 5
TTL_DEFAULT = 5

# ── Mesh State ────────────────────────────────────────────────────────────────
CACHE_SIZE  = 30
seen_msgs   = []
my_msg_id   = 0
relay_count = 0

# ── Serial buffer ─────────────────────────────────────────────────────────────
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

# ── Hardware Init ─────────────────────────────────────────────────────────────
try:
    rf_sw = digitalio.DigitalInOut(rf_sw_pin)
    rf_sw.direction = digitalio.Direction.OUTPUT
    rf_sw.value = False                       # RX mode

    spi  = busio.SPI(sck_pin, mosi_pin, miso_pin)
    lora = SX1262(spi, sck_pin, mosi_pin, miso_pin,
                  nss_pin, dio1_pin, rst_pin, busy_pin)
    lora.begin(freq=MESH_FREQ, bw=BW, sf=SF, cr=CR,
               useRegulatorLDO=True, tcxoVoltage=1.8, power=22)
    print(f"Node {NODE_ID}  {MESH_FREQ} MHz  SF{SF}  TTL={TTL_DEFAULT}")
except Exception as e:
    print(f"LoRa FAIL: {e}")
    raise

# ── Helpers ───────────────────────────────────────────────────────────────────
def already_seen(src, mid):
    return (src, mid) in seen_msgs

def mark_seen(src, mid):
    seen_msgs.append((src, mid))
    if len(seen_msgs) > CACHE_SIZE:
        seen_msgs.pop(0)

def encode_pkt(src, dst, mid, ttl, payload):
    return f"M:{src}:{dst}:{mid}:{ttl}:{payload}".encode()

def decode_pkt(raw):
    try:
        s = raw.decode().strip()
        if not s.startswith("M:"):
            return None
        parts = s[2:].split(":", 4)
        if len(parts) < 5:
            return None
        return int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]), parts[4]
    except:
        return None

def lora_send(pkt_bytes):
    """Transmit bytes — toggles RF switch to TX path and back."""
    rf_sw.value = True
    lora.send(pkt_bytes)
    rf_sw.value = False

def mesh_send(payload, dst=0):
    """Originate a new mesh packet from this node."""
    global my_msg_id
    my_msg_id = (my_msg_id + 1) % 256
    mark_seen(NODE_ID, my_msg_id)
    lora_send(encode_pkt(NODE_ID, dst, my_msg_id, TTL_DEFAULT, payload))

# ── Main Loop ─────────────────────────────────────────────────────────────────
print("Mesh relay running...")
last_beacon = time.monotonic()

while True:
    # Serial input — read and buffer characters, process on newline
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
                    print(f"Serial TX: {text}")
                    mesh_send(text)
    except Exception as e:
        print(f"Serial err: {e}")

    # RX + relay
    try:
        result = lora.recv(timeout_en=True, timeout_ms=300)
        if result and isinstance(result, tuple) and len(result) == 2:
            data, _ = result
            if data:
                pkt = decode_pkt(data)
                if pkt:
                    src, dst, mid, ttl, payload = pkt
                    rssi = lora.getRSSI()
                    snr  = lora.getSNR()

                    if not already_seen(src, mid):
                        mark_seen(src, mid)
                        print(f"RX src={src} dst={dst} mid={mid} ttl={ttl} rssi={rssi} snr={snr:.1f}  '{payload}'")

                        # Always relay if TTL allows (flooding delivers regardless of dst)
                        if ttl > 1:
                            relay_count += 1
                            time.sleep(0.05 * (NODE_ID % 5))
                            lora_send(encode_pkt(src, dst, mid, ttl - 1, payload))
                            print(f"  → relayed (total relays: {relay_count})")

                        # Only act on payload if broadcast or addressed to this node
                        if dst == 0 or dst == NODE_ID:
                            if payload == "DISC":
                                time.sleep(0.05 * (NODE_ID % 5))
                                mesh_send(f"BCN:{NODE_ID}")
                                print(f"  → discovery reply BCN:{NODE_ID}")
                            elif payload.startswith("PARROT:"):
                                time.sleep(0.15)
                                mesh_send(f"PONG:{NODE_ID}:{payload[7:]}")
                                print(f"  → PONG sent for parrot")
    except Exception as e:
        print(f"RX err: {e}")

    # Periodic beacon
    now = time.monotonic()
    if now - last_beacon >= 10:
        last_beacon = now
        mesh_send(f"BCN:{NODE_ID}")
        print(f"TX beacon BCN:{NODE_ID}")

    time.sleep(0.01)
