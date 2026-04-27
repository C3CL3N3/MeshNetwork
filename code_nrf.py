# SPDX-FileCopyrightText: 2026 Student Lab - COMP 4531 - HKUST
# SPDX-License-Identifier: MIT
#
# LoRa Mesh Node — XIAO nRF52840 Sense
# Flooding mesh with TTL-based deduplication.
# BLE exposes a single control characteristic for dashboard commands/notifications.

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
GROUP_ID = 0      # ← change per board (1–30); sets BLE name and LoRa freq
NODE_ID  = GROUP_ID

# ── LoRa Parameters ───────────────────────────────────────────────────────────
MY_FREQ     = 900.0 + (GROUP_ID - 1) * 1.0   # MHz, unique per group
BW          = 125.0   # kHz
SF          = 7       # Spreading Factor — all mesh nodes must use the same value
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
    lora.begin(freq=MY_FREQ, bw=BW, sf=SF, cr=CR,
               useRegulatorLDO=True, tcxoVoltage=1.6)
    lora_ok = True
    print(f"LoRa OK  {MY_FREQ} MHz  SF{SF}  BW{BW}")
except Exception as e:
    print(f"LoRa FAIL: {e}")

# ── BLE Service ───────────────────────────────────────────────────────────────
gid_hex   = f"{GROUP_ID:02x}"
SVC_UUID  = VendorUUID(f"13172b58-{gid_hex}40-4150-b42d-22f30b0a0499")
CTRL_UUID = VendorUUID(f"13172b58-{gid_hex}42-4150-b42d-22f30b0a0499")

class MeshService(Service):
    uuid    = SVC_UUID
    control = Characteristic(
        uuid=CTRL_UUID,
        properties=( Characteristic.WRITE
                   | Characteristic.WRITE_NO_RESPONSE
                   | Characteristic.READ
                   | Characteristic.NOTIFY ),
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

def encode_pkt(src, mid, ttl, payload):
    return f"M:{src}:{mid}:{ttl}:{payload}".encode()

def decode_pkt(raw):
    try:
        s = raw.decode().strip()
        if not s.startswith("M:"):
            return None
        parts = s[2:].split(":", 3)
        if len(parts) < 4:
            return None
        return int(parts[0]), int(parts[1]), int(parts[2]), parts[3]
    except:
        return None

def lora_tx(src, mid, ttl, payload):
    try:
        lora.send(encode_pkt(src, mid, ttl, payload))
    except Exception as e:
        print(f"TX err: {e}")

def ble_notify(msg):
    """Push a notification to the connected BLE central (dashboard)."""
    try:
        mesh_svc.control = msg.encode()[:100]
    except:
        pass

def lora_rx_and_relay():
    """Non-blocking LoRa receive with flood relay. Safe to call from any loop."""
    global relay_count
    if not lora_ok:
        return
    try:
        data, _ = lora.recv()
        if not data:
            return
        pkt = decode_pkt(data)
        if not pkt:
            return
        src, mid, ttl, payload = pkt
        rssi = lora.getRSSI()
        snr  = lora.getSNR()

        if already_seen(src, mid):
            return                            # duplicate — drop silently
        mark_seen(src, mid)

        blink(1)
        print(f"RX src={src} mid={mid} ttl={ttl} rssi={rssi} snr={snr:.1f} '{payload}'")
        ble_notify(f"MESH_RX:{src}|{mid}|{ttl}|{rssi}|{snr:.1f}|{payload}")

        if ttl > 1:
            relay_count += 1
            time.sleep(0.05 * (NODE_ID % 5))  # stagger rebroadcast to reduce collisions
            lora_tx(src, mid, ttl - 1, payload)
    except Exception as e:
        print(f"RX err: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────
print(f"Node {NODE_ID}  {MY_FREQ} MHz  SF{SF}  TTL={TTL_DEFAULT}")
blink(3)

while True:
    # Advertise until a central (dashboard) connects
    ble.start_advertising(adv)
    while not ble.connected:
        led.value = False; time.sleep(0.15)
        led.value = True;  time.sleep(0.85)
        lora_rx_and_relay()               # keep relaying even while BLE is unconnected

    ble.stop_advertising()
    print("BLE connected")
    blink(5)
    mesh_svc.control = b''

    while ble.connected:
        # ── BLE command handler ───────────────────────────────────────────────
        try:
            val = mesh_svc.control
            if val and len(val) > 1:
                cmd = val.decode('utf-8', 'ignore').strip().replace('\x00', '')
                mesh_svc.control = b''    # clear immediately after reading

                # Skip our own notification echoes (peripheral reads back what it wrote)
                if cmd and not cmd.startswith('MESH_'):
                    blink(1)
                    print(f"CMD: {cmd}")

                    if cmd.startswith('SEND_MESH:') and lora_ok:
                        my_msg_id = (my_msg_id + 1) % 256
                        payload   = cmd[10:]
                        mark_seen(NODE_ID, my_msg_id)
                        lora_tx(NODE_ID, my_msg_id, TTL_DEFAULT, payload)
                        ble_notify(f"MESH_TX:{NODE_ID}|{my_msg_id}|{TTL_DEFAULT}|{payload}")
        except:
            pass

        # ── LoRa RX + relay ───────────────────────────────────────────────────
        lora_rx_and_relay()
        time.sleep(0.001)

    print("BLE disconnected")
