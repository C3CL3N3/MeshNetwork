# SPDX-FileCopyrightText: 2026 Student Lab - COMP 4531 - HKUST
# SPDX-License-Identifier: MIT
#
# LoRa Mesh Node — XIAO nRF52840 Sense
# Flooding mesh with TTL-based deduplication.
# BLE exposes two characteristics: cmd_rx (central→node) and data_tx (node→central).

import time
import board
import busio
import digitalio
import adafruit_ble
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
from adafruit_ble.services import Service
from adafruit_ble.uuid import VendorUUID
from adafruit_ble.characteristics import Characteristic
from sx1262 import SX1262

# ── Identity ──────────────────────────────────────────────────────────────────
GROUP_ID  = 13    # Lab group → sets BLE UUID and device name (1–30)
NODE_ID   = 1     # ← unique per physical board within the mesh (e.g. 1, 2, 3…)

# ── LoRa Parameters ───────────────────────────────────────────────────────────
# MESH_FREQ must be identical on every node — it is NOT derived from GROUP_ID.
MESH_FREQ   = 912.0   # MHz — shared mesh channel; change all boards together
BW          = 125.0   # kHz
SF          = 7       # Spreading Factor — must match on all nodes
CR          = 5       # Coding rate 4/5
TTL_DEFAULT = 5       # Maximum relay hops

# ── Mesh State ────────────────────────────────────────────────────────────────
CACHE_SIZE  = 30
seen_msgs   = []      # [(src_id, msg_id), ...]  rolling dedup window
my_msg_id   = 0       # outgoing sequence counter 0–255
relay_count = 0

# ── Pins ──────────────────────────────────────────────────────────────────────
lora_sck  = board.D8
lora_miso = board.D9
lora_mosi = board.D10
lora_nss  = board.D4
lora_rst  = board.D2
lora_busy = board.D3
lora_dio1 = board.D1
rf_sw_pin = board.D5

# ── Hardware Init ─────────────────────────────────────────────────────────────
led = digitalio.DigitalInOut(board.LED_BLUE)
led.direction = digitalio.Direction.OUTPUT
led.value = True                              # OFF (active-low on XIAO)

lora_ok = False
try:
    rf_sw = digitalio.DigitalInOut(rf_sw_pin)
    rf_sw.direction = digitalio.Direction.OUTPUT
    rf_sw.value = False                       # RX mode
    spi  = busio.SPI(lora_sck, lora_mosi, lora_miso)
    lora = SX1262(spi, lora_sck, lora_mosi, lora_miso,
                  lora_nss, lora_dio1, lora_rst, lora_busy)
    lora.begin(freq=MESH_FREQ, bw=BW, sf=SF, cr=CR,
               useRegulatorLDO=True, tcxoVoltage=1.6)
    lora_ok = True
    print(f"LoRa OK  {MESH_FREQ} MHz  SF{SF}  BW{BW}")
except Exception as e:
    print(f"LoRa FAIL: {e}")

# ── BLE Service ───────────────────────────────────────────────────────────────
# Two separate characteristics — no shared write/notify ambiguity:
#   cmd_rx  (UUID …41…): central writes commands here; peripheral polls it
#   data_tx (UUID …42…): peripheral writes notifications here; central subscribes
gid_hex    = f"{GROUP_ID:02x}"
SVC_UUID   = VendorUUID(f"13172b58-{gid_hex}40-4150-b42d-22f30b0a0499")
CMD_UUID   = VendorUUID(f"13172b58-{gid_hex}41-4150-b42d-22f30b0a0499")
NOTIF_UUID = VendorUUID(f"13172b58-{gid_hex}42-4150-b42d-22f30b0a0499")

class MeshService(Service):
    uuid    = SVC_UUID
    cmd_rx  = Characteristic(
        uuid=CMD_UUID,
        properties=(Characteristic.WRITE | Characteristic.WRITE_NO_RESPONSE),
        max_length=100
    )
    data_tx = Characteristic(
        uuid=NOTIF_UUID,
        properties=(Characteristic.READ | Characteristic.NOTIFY),
        max_length=100
    )

ble      = adafruit_ble.BLERadio()
ble.name = f"MESH_G{GROUP_ID}"
mesh_svc = MeshService()
adv      = ProvideServicesAdvertisement(mesh_svc)

# ── Helpers ───────────────────────────────────────────────────────────────────
def blink(n=1):
    for _ in range(n):
        led.value = False; time.sleep(0.05)
        led.value = True;  time.sleep(0.05)

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

def lora_tx(src, dst, mid, ttl, payload):
    try:
        rf_sw.value = True                    # flip antenna to TX path
        lora.send(encode_pkt(src, dst, mid, ttl, payload))
        rf_sw.value = False                   # flip back to RX path
        print(f"TX src={src} dst={dst} mid={mid} ttl={ttl} '{payload}'")
    except Exception as e:
        rf_sw.value = False
        print(f"TX err: {e}")

def ble_notify(msg):
    """Push a string notification to the connected central via data_tx."""
    try:
        mesh_svc.data_tx = msg.encode()[:100]
    except Exception as e:
        print(f"notify err: {e}")

def lora_rx_and_relay():
    """Non-blocking LoRa receive with flood relay."""
    global relay_count
    if not lora_ok:
        return
    try:
        result = lora.recv(timeout_en=True, timeout_ms=300)
        if not result or not isinstance(result, tuple) or len(result) < 2:
            return
        data, _ = result
        if not data:
            return
        pkt = decode_pkt(data)
        if not pkt:
            return
        src, dst, mid, ttl, payload = pkt
        rssi = lora.getRSSI()
        snr  = lora.getSNR()

        if already_seen(src, mid):
            return
        mark_seen(src, mid)

        blink(1)
        print(f"RX src={src} dst={dst} mid={mid} ttl={ttl} rssi={rssi} snr={snr:.1f} '{payload}'")

        # Only process payload (notify BLE) if broadcast or addressed to this node
        if dst == 0 or dst == NODE_ID:
            ble_notify(f"MESH_RX:{src}|{dst}|{mid}|{ttl}|{rssi}|{snr:.1f}|{payload}")

        # Always relay if TTL allows (flooding delivers regardless of dst)
        if ttl > 1:
            relay_count += 1
            time.sleep(0.05 * (NODE_ID % 5))
            lora_tx(src, dst, mid, ttl - 1, payload)
    except Exception as e:
        print(f"RX err: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────
print(f"Node {NODE_ID}  {MESH_FREQ} MHz  SF{SF}  TTL={TTL_DEFAULT}")
blink(3)

while True:
    ble.start_advertising(adv)
    while not ble.connected:
        led.value = False; time.sleep(0.15)
        led.value = True;  time.sleep(0.85)
        lora_rx_and_relay()

    ble.stop_advertising()
    print("BLE connected")
    blink(5)

    # Wait for browser to complete startNotifications(), then introduce ourselves
    time.sleep(1.5)
    ble_notify(f"MESH_INFO:NODE_ID:{NODE_ID}")

    # Broadcast discovery so all mesh nodes announce themselves immediately
    if lora_ok:
        my_msg_id = (my_msg_id + 1) % 256
        mark_seen(NODE_ID, my_msg_id)
        lora_tx(NODE_ID, 0, my_msg_id, TTL_DEFAULT, "DISC")
        print("TX discovery broadcast")

    last_ping = time.monotonic()
    ping_n    = 0

    while ble.connected:
        # ── Heartbeat — fires every 5 s regardless of commands ────────────────
        now = time.monotonic()
        if now - last_ping >= 5.0:
            last_ping = now
            ping_n += 1
            ble_notify(f"MESH_PING:{ping_n}")
            print(f"PING {ping_n}")

        # ── BLE command handler (reads cmd_rx, never interferes with data_tx) ─
        try:
            val = mesh_svc.cmd_rx
            if val and len(val) > 1:
                cmd = val.decode('utf-8', 'ignore').strip().replace('\x00', '')
                mesh_svc.cmd_rx = b''          # clear so same cmd isn't re-processed
                if cmd:
                    blink(1)
                    print(f"CMD: {cmd}")

                    if cmd.startswith('PARROT:'):
                        ble_notify(f"MESH_PARROT:{cmd[7:]}")

                    elif cmd.startswith('SEND_MESH:'):
                        if lora_ok:
                            my_msg_id = (my_msg_id + 1) % 256
                            payload   = cmd[10:]
                            mark_seen(NODE_ID, my_msg_id)
                            lora_tx(NODE_ID, 0, my_msg_id, TTL_DEFAULT, payload)
                            ble_notify(f"MESH_TX:{NODE_ID}|0|{my_msg_id}|{TTL_DEFAULT}|{payload}")
                        else:
                            ble_notify("MESH_ERR:LORA_FAIL")

                    elif cmd.startswith('SEND_NODE:'):
                        if lora_ok:
                            # Format: SEND_NODE:<dst>:<text>
                            rest = cmd[10:]
                            colon = rest.find(':')
                            if colon > 0:
                                dst     = int(rest[:colon])
                                payload = rest[colon + 1:]
                                my_msg_id = (my_msg_id + 1) % 256
                                mark_seen(NODE_ID, my_msg_id)
                                lora_tx(NODE_ID, dst, my_msg_id, TTL_DEFAULT, payload)
                                ble_notify(f"MESH_TX:{NODE_ID}|{dst}|{my_msg_id}|{TTL_DEFAULT}|{payload}")
                        else:
                            ble_notify("MESH_ERR:LORA_FAIL")
        except Exception as e:
            print(f"loop err: {e}")

        # ── LoRa RX + relay ───────────────────────────────────────────────────
        lora_rx_and_relay()
        time.sleep(0.001)

    print("BLE disconnected")
