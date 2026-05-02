# SPDX-FileCopyrightText: 2026 Student Lab - COMP 4531 - HKUST
# SPDX-License-Identifier: MIT
#
# LoRa Mesh BLE Gateway — XIAO nRF52840 Sense + SX1262
# Protocol: H/R/D distance-vector mesh, fixed SF7.
#
# BLE commands (central → node):
#   SEND_MESH:<text>       broadcast DATA
#   SEND_NODE:<dst>:<text> unicast DATA to node dst
#   PARROT:<text>          BLE loopback test
#   ROUTES                 dump routing table
#   NEIGHBORS              dump neighbor table
#
# BLE notifications (node → central):
#   MESH_INFO:NODE_ID:<n>
#   MESH_PING:<n>
#   MESH_RX:<src>|<dst>|<mid>|<ttl>|<rssi>|<snr>|<payload>
#   MESH_TX:<src>|<dst>|<nh>|<mid>|<ttl>|<payload>
#   MESH_ROUTE:<dest>|<next_hop>|<hops>
#   MESH_NB:<node>|<rssi>|<snr>
#   MESH_ERR:LORA_FAIL
#   MESH_ERR:NO_ROUTE:<dst>
#   MESH_PARROT:<text>

import time
import random
import board
import busio
import digitalio
import adafruit_ble
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
from adafruit_ble.services import Service
from adafruit_ble.uuid import VendorUUID
from adafruit_ble.characteristics import Characteristic
import mesh_common as mc
from sx1262 import SX1262

# ── Identity ──────────────────────────────────────────────────────────────────
GROUP_ID = 13
NODE_ID  = 1

# ── LoRa parameters ───────────────────────────────────────────────────────────
MESH_FREQ = 912.0
BW        = 125.0
CR        = 5

# ── Pins ──────────────────────────────────────────────────────────────────────
lora_sck  = board.D8
lora_miso = board.D9
lora_mosi = board.D10
lora_nss  = board.D4
lora_rst  = board.D2
lora_busy = board.D3
lora_dio1 = board.D1
rf_sw_pin = board.D5

# ── Hardware init ─────────────────────────────────────────────────────────────
led = digitalio.DigitalInOut(board.LED_BLUE)
led.direction = digitalio.Direction.OUTPUT
led.value = True  # OFF (active-low)

lora_ok = False
try:
    spi  = busio.SPI(lora_sck, lora_mosi, lora_miso)
    lora = SX1262(spi, lora_sck, lora_mosi, lora_miso,
                  lora_nss, lora_dio1, lora_rst, lora_busy, rf_sw=rf_sw_pin)
    lora.begin(freq=MESH_FREQ, bw=BW, sf=mc.SF, cr=CR,
               useRegulatorLDO=True, tcxoVoltage=1.8)
    lora_ok = True
    print("LoRa OK  {} MHz  SF{}".format(MESH_FREQ, mc.SF))
except Exception as e:
    print("LoRa FAIL: {}".format(e))

# ── BLE service ───────────────────────────────────────────────────────────────
gid_hex    = "{:02x}".format(GROUP_ID)
SVC_UUID   = VendorUUID("13172b58-{}40-4150-b42d-22f30b0a0499".format(gid_hex))
CMD_UUID   = VendorUUID("13172b58-{}41-4150-b42d-22f30b0a0499".format(gid_hex))
NOTIF_UUID = VendorUUID("13172b58-{}42-4150-b42d-22f30b0a0499".format(gid_hex))

class MeshService(Service):
    uuid    = SVC_UUID
    cmd_rx  = Characteristic(
        uuid=CMD_UUID,
        properties=(Characteristic.WRITE | Characteristic.WRITE_NO_RESPONSE),
        max_length=100)
    data_tx = Characteristic(
        uuid=NOTIF_UUID,
        properties=(Characteristic.READ | Characteristic.NOTIFY),
        max_length=100)

ble      = adafruit_ble.BLERadio()
ble.name = "MESH_G{}".format(GROUP_ID)
mesh_svc = MeshService()
adv      = ProvideServicesAdvertisement(mesh_svc)

# ── Node state ────────────────────────────────────────────────────────────────
my_msg_id    = 0
my_route_mid = 0

# ── Helpers ───────────────────────────────────────────────────────────────────
def blink(n=1):
    for _ in range(n):
        led.value = False; time.sleep(0.05)
        led.value = True;  time.sleep(0.05)

def ble_notify(msg):
    if not ble.connected:
        return
    try:
        mesh_svc.data_tx = msg.encode()[:100]
    except Exception:
        pass

def _lora_tx(pkt_bytes):
    lora.send(pkt_bytes)

def _lora_tx_lbt(pkt_bytes):
    if not lora.send_lbt(pkt_bytes, max_tries=3, base_backoff_ms=20):
        print("  LBT: dropped")

def _relay_prob(rssi):
    if rssi > -60:  return 0.40
    if rssi > -75:  return 0.65
    if rssi > -90:  return 0.85
    return 0.97

# ── Transmit ──────────────────────────────────────────────────────────────────
def send_hello():
    if not lora_ok:
        return
    _lora_tx(mc.encode_hello(NODE_ID))
    print("TX H N{}".format(NODE_ID))

def send_route_ad_self():
    global my_route_mid
    if not lora_ok:
        return
    my_route_mid = (my_route_mid + 1) % 256
    _lora_tx(mc.encode_route_ad(NODE_ID, NODE_ID, my_route_mid, 0))
    print("TX R mid={}".format(my_route_mid))

def send_data(dst, payload):
    global my_msg_id
    if not lora_ok:
        ble_notify("MESH_ERR:LORA_FAIL")
        print("TX D  FAIL lora_ok=False")
        return False
    my_msg_id = (my_msg_id + 1) % 256
    mc.data_mark(NODE_ID, my_msg_id)
    nh = 0 if dst == 0 else mc.route_next_hop(dst)
    if dst != 0 and nh is None:
        ble_notify("MESH_ERR:NO_ROUTE:{}".format(dst))
        print("TX D  no route to N{}".format(dst))
        return False
    pkt = mc.encode_data(NODE_ID, dst, nh, my_msg_id, mc.TTL_DEFAULT, payload)
    _lora_tx(pkt)
    ble_notify("MESH_TX:{}|{}|{}|{}|{}|{}".format(
        NODE_ID, dst, nh, my_msg_id, mc.TTL_DEFAULT, payload))
    print("TX D  dst=N{} nh=N{} mid={} '{}'".format(dst, nh if nh else 0, my_msg_id, payload))
    return True

# ── Receive handlers ──────────────────────────────────────────────────────────
def _handle_hello(src, rssi, snr):
    if src == NODE_ID:
        return
    mc.neighbor_update(src, snr, rssi)
    ble_notify("MESH_NB:{}|{}|{:.1f}".format(src, rssi, snr))
    print("RX H  src=N{} rssi={} snr={:.1f}".format(src, rssi, snr))

def _handle_route_ad(pkt, rssi, snr):
    orig, fwd, mid, hops = pkt
    if orig == NODE_ID or mc.route_seen(orig, mid):
        print("RX R  orig=N{} fwd=N{} mid={} hops={} [dup]".format(orig, fwd, mid, hops))
        return
    mc.route_mark(orig, mid)
    mc.neighbor_update(fwd, snr, rssi)
    link_rssi = mc.neighbor.get(fwd, {}).get('rssi')
    improved = mc.route_update(orig, fwd, hops, link_rssi)
    r = mc.route_table.get(orig, {})
    print("RX R  orig=N{} fwd=N{} mid={} hops={} -> nh=N{} total={} {}".format(
        orig, fwd, mid, hops,
        r.get('next_hop', '?'), r.get('hops', '?'),
        "[NEW]" if improved else "[known]"))
    if improved:
        ble_notify("MESH_ROUTE:{}|{}|{}".format(orig, r['next_hop'], r['hops']))
    if hops + 1 < mc.ROUTE_TTL:
        time.sleep(random.uniform(0.02, 0.12))
        print("  relay R orig=N{} hops={}".format(orig, hops + 1))
        _lora_tx_lbt(mc.encode_route_ad(orig, NODE_ID, mid, hops + 1))

def _handle_data(pkt, rssi, snr):
    src, dst, next_hop, mid, ttl, payload = pkt
    if src == NODE_ID or mc.data_seen(src, mid):
        print("RX D  src=N{} dst=N{} mid={} [dup/self]".format(src, dst, mid))
        return
    mc.data_mark(src, mid)
    print("RX D  src=N{} dst=N{} nh=N{} mid={} ttl={} rssi={} '{}'".format(
        src, dst, next_hop, mid, ttl, rssi, payload))
    if dst == 0 or dst == NODE_ID:
        ble_notify("MESH_RX:{}|{}|{}|{}|{}|{:.1f}|{}".format(
            src, dst, mid, ttl, rssi, snr, payload))
        _deliver(src, dst, payload)
    if dst == NODE_ID or ttl <= 1:
        return
    if next_hop == 0:
        if random.random() > _relay_prob(rssi):
            print("  flood relay skipped (prob)")
            return
        time.sleep(random.uniform(0.05, 0.20))
        print("  relay D flood src=N{} dst=N{} ttl={}".format(src, dst, ttl - 1))
        _lora_tx_lbt(mc.encode_data(src, dst, 0, mid, ttl - 1, payload))
    elif next_hop == NODE_ID:
        new_nh = mc.route_next_hop(dst)
        if new_nh is None:
            print("  no route to N{}".format(dst))
            return
        time.sleep(random.uniform(0.05, 0.15))
        print("  relay D unicast src=N{} dst=N{} new_nh=N{} ttl={}".format(
            src, dst, new_nh, ttl - 1))
        _lora_tx_lbt(mc.encode_data(src, dst, new_nh, mid, ttl - 1, payload))

def _deliver(src, dst, payload):
    print("  DELIVER src={} dst={}: '{}'".format(src, dst, payload))
    if payload.startswith("PARROT:"):
        time.sleep(0.15)
        send_data(src, "PONG:{}:{}".format(NODE_ID, payload[7:]))

# ── RX cycle ──────────────────────────────────────────────────────────────────
def rx_cycle():
    if not lora_ok:
        return
    try:
        result = lora.recv(timeout_en=True, timeout_ms=300)
        if not (result and isinstance(result, tuple) and len(result) >= 2 and result[0]):
            return
        data, _ = result
        rssi = lora.getRSSI()
        snr  = lora.getSNR()
        s = data.decode('utf-8', 'ignore').strip()
        if s.startswith("H:"):
            src = mc.decode_hello(data)
            if src is not None:
                _handle_hello(src, rssi, snr)
        elif s.startswith("R:"):
            pkt = mc.decode_route_ad(data)
            if pkt:
                _handle_route_ad(pkt, rssi, snr)
        elif s.startswith("D:"):
            pkt = mc.decode_data(data)
            if pkt:
                _handle_data(pkt, rssi, snr)
    except Exception as e:
        print("RX err: {}".format(e))

# ── BLE command handler ───────────────────────────────────────────────────────
def _handle_ble_cmd(cmd):
    if cmd.startswith("PARROT:"):
        ble_notify("MESH_PARROT:{}".format(cmd[7:]))
    elif cmd.startswith("SEND_MESH:"):
        send_data(0, cmd[10:])
    elif cmd.startswith("SEND_NODE:"):
        rest = cmd[10:]; colon = rest.find(":")
        if colon > 0:
            send_data(int(rest[:colon]), rest[colon + 1:])
    elif cmd == "ROUTES":
        for dest, r in mc.route_table.items():
            ble_notify("MESH_ROUTE:{}|{}|{}".format(dest, r['next_hop'], r['hops']))
    elif cmd == "NEIGHBORS":
        for nid, nb in mc.neighbor.items():
            ble_notify("MESH_NB:{}|{}|{:.1f}".format(nid, nb['rssi'], nb['snr']))

# ── Periodic ──────────────────────────────────────────────────────────────────
def _periodic(now):
    global last_hello, last_route_ad, last_expire
    if now - last_hello >= mc.HELLO_INTERVAL:
        last_hello = now
        send_hello()
    if now - last_route_ad >= mc.ROUTE_AD_INTERVAL:
        last_route_ad = now
        send_route_ad_self()
    if now - last_expire >= 30:
        last_expire = now
        mc.neighbor_expire()
        mc.route_expire()

# ── Main ──────────────────────────────────────────────────────────────────────
print("Node {}  {} MHz  SF7".format(NODE_ID, MESH_FREQ))
blink(3)

last_hello    = -random.uniform(0, mc.HELLO_INTERVAL * 0.9)
last_route_ad = -random.uniform(0, mc.ROUTE_AD_INTERVAL * 0.9)
last_expire   = 0.0

while True:
    ble.start_advertising(adv)
    while not ble.connected:
        led.value = not led.value
        now = time.monotonic()
        _periodic(now)
        rx_cycle()
        time.sleep(0.1)

    ble.stop_advertising()
    led.value = True
    print("BLE connected")
    blink(5)

    if lora_ok:
        send_data(0, "DISC:{}".format(NODE_ID))

    time.sleep(1.5)
    ble_notify("MESH_INFO:NODE_ID:{}".format(NODE_ID))

    last_ping = time.monotonic()
    ping_n    = 0

    while ble.connected:
        now = time.monotonic()
        _periodic(now)

        if now - last_ping >= 5.0:
            last_ping = now
            ping_n   += 1
            ble_notify("MESH_PING:{}".format(ping_n))

        try:
            val = mesh_svc.cmd_rx
            if val and len(val) > 1:
                cmd = val.decode('utf-8', 'ignore').strip().replace('\x00', '')
                mesh_svc.cmd_rx = b''
                if cmd:
                    blink(1)
                    print("CMD: {}".format(cmd))
                    _handle_ble_cmd(cmd)
        except Exception as e:
            print("BLE cmd err: {}".format(e))

        rx_cycle()
        time.sleep(0.001)

    print("BLE disconnected")
