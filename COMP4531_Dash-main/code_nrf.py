# SPDX-FileCopyrightText: 2026 Student Lab - COMP 4531 - HKUST
# SPDX-License-Identifier: MIT
#
# LoRa Mesh BLE Gateway — XIAO nRF52840 Sense + SX1262
# Protocol: H/R/D three-packet distance-vector mesh with adaptive SF.
# BLE exposes two characteristics (same UUIDs as before):
#   cmd_rx  (…41…): central writes commands → node
#   data_tx (…42…): node pushes events     → central
#
# BLE commands (central → node):
#   SEND_MESH:<text>          broadcast DATA
#   SEND_NODE:<dst>:<text>    unicast DATA to node dst
#   PARROT:<text>             BLE loopback test (no LoRa)
#   ROUTES                    dump routing table via notifications
#   NEIGHBORS                 dump neighbor table via notifications
#
# BLE notifications (node → central):
#   MESH_INFO:NODE_ID:<n>|SF:<sf>        sent 1.5 s after connect
#   MESH_PING:<n>                        heartbeat every 5 s
#   MESH_RX:<src>|<dst>|<mid>|<ttl>|<rssi>|<snr>|<payload>
#   MESH_TX:<src>|<dst>|<nh>|<mid>|<ttl>|<payload>
#   MESH_ROUTE:<dest>|<next_hop>|<hops>|<cost>
#   MESH_NB:<node>|<rssi>|<snr>|<sf>[|ASF:<old>-><new>]
#   MESH_SF:<new_sf>                     when network SF adapts
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
import logger

# ── Identity ──────────────────────────────────────────────────────────────────
GROUP_ID = 13  # sets BLE UUID and device name
NODE_ID  = 1   # gateway is always node 1

# ── LoRa hardware parameters ──────────────────────────────────────────────────
MESH_FREQ = 912.0
BW        = 125.0
CR        = 5

# ── Pins (nRF52840) ───────────────────────────────────────────────────────────
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
led.value = True  # OFF (active-low on XIAO)

lora_ok = False
try:
    spi   = busio.SPI(lora_sck, lora_mosi, lora_miso)
    rf_sw = digitalio.DigitalInOut(rf_sw_pin)
    rf_sw.direction = digitalio.Direction.OUTPUT
    rf_sw.value = False
    lora  = SX1262(spi, lora_sck, lora_mosi, lora_miso,
                   lora_nss, lora_dio1, lora_rst, lora_busy)
    lora.begin(freq=MESH_FREQ, bw=BW, sf=mc.network_sf, cr=CR,
               useRegulatorLDO=True, tcxoVoltage=1.6)
    lora_ok = True
    print("LoRa OK  {} MHz  SF{}".format(MESH_FREQ, mc.network_sf))
    logger.init()
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
my_msg_id      = 0
my_route_mid   = 0
_active_sf     = mc.network_sf
_sf_good_since = None

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

def _radio_set_sf(sf):
    global _active_sf
    if sf == _active_sf:
        return
    lora.begin(freq=MESH_FREQ, bw=BW, sf=sf, cr=CR,
               useRegulatorLDO=True, tcxoVoltage=1.6)
    _active_sf = sf
    print("RADIO SF->{}".format(sf))

_last_tx = 0.0

def _lora_tx(pkt_bytes):
    global _last_tx
    rf_sw.value = True
    lora.send(pkt_bytes)
    rf_sw.value = False
    _last_tx = time.monotonic()
    logger.log("TX {}".format(pkt_bytes.decode('utf-8', 'ignore').strip()))

def _lora_tx_lbt(pkt_bytes):
    global _last_tx
    for attempt in range(5):
        result = lora.recv(timeout_en=True, timeout_ms=25)
        if not (result and isinstance(result, tuple) and result[0]):
            rf_sw.value = True
            lora.send(pkt_bytes)
            rf_sw.value = False
            _last_tx = time.monotonic()
            return
        time.sleep(0.06 * (2 ** attempt) + random.uniform(0, 0.04))
    print("  LBT: relay dropped")

def _relay_prob(rssi):
    if rssi > -60:  return 0.40
    if rssi > -75:  return 0.65
    if rssi > -90:  return 0.85
    return 0.97

# ── Transmit functions ────────────────────────────────────────────────────────
def send_hello():
    if not lora_ok:
        return
    _lora_tx(mc.encode_hello(NODE_ID, mc.network_sf))

def send_route_ad_self():
    global my_route_mid
    if not lora_ok:
        return
    my_route_mid = (my_route_mid + 1) % 256
    _lora_tx(mc.encode_route_ad(NODE_ID, NODE_ID, my_route_mid, 0, 0))

def send_data(dst, payload):
    global my_msg_id
    if not lora_ok:
        ble_notify("MESH_ERR:LORA_FAIL")
        return False
    my_msg_id = (my_msg_id + 1) % 256
    mc.data_mark(NODE_ID, my_msg_id)
    if dst == 0:
        nh = 0
    else:
        nh = mc.route_next_hop(dst)
        if nh is None:
            print("No route to N{}".format(dst))
            ble_notify("MESH_ERR:NO_ROUTE:{}".format(dst))
            return False
    pkt = mc.encode_data(NODE_ID, dst, nh, my_msg_id, mc.TTL_DEFAULT, payload)
    _lora_tx(pkt)
    ble_notify("MESH_TX:{}|{}|{}|{}|{}|{}".format(
        NODE_ID, dst, nh, my_msg_id, mc.TTL_DEFAULT, payload))
    print("TX D dst={} nh={} mid={} '{}'".format(dst, nh, my_msg_id, payload))
    return True

# ── Receive handlers ──────────────────────────────────────────────────────────
def _handle_hello(pkt, rssi, snr):
    src, src_sf = pkt
    if src == NODE_ID:
        return
    old_sf, new_sf = mc.neighbor_update(src, snr, rssi)
    sf_tag = "|ASF:{}->{}" .format(old_sf, new_sf) if new_sf != old_sf else ""
    ble_notify("MESH_NB:{}|{}|{:.1f}|{}{}".format(src, rssi, snr, new_sf, sf_tag))
    print("H  N{} sf={} rssi={} snr={:.1f}{}".format(src, src_sf, rssi, snr, sf_tag))

def _handle_route_ad(pkt, rssi, snr):
    orig, fwd, mid, hops, cost = pkt
    if orig == NODE_ID:
        return
    if mc.route_seen(orig, mid):
        return
    mc.route_mark(orig, mid)
    mc.neighbor_update(fwd, snr, rssi)
    improved = mc.route_update(orig, fwd, hops, cost)
    if improved:
        r = mc.route_table[orig]
        ble_notify("MESH_ROUTE:{}|{}|{}|{}".format(
            orig, r['next_hop'], r['hops'], r['cost']))
        print("Route N{}: nh={} hops={} cost={}".format(
            orig, r['next_hop'], r['hops'], r['cost']))
    if hops + 1 < mc.ROUTE_TTL:
        nb  = mc.neighbor.get(fwd)
        link = mc.SF_AIRTIME[nb['sf']] if nb else mc.SF_AIRTIME[mc.network_sf]
        time.sleep(random.uniform(0.02, 0.12))
        _lora_tx_lbt(mc.encode_route_ad(orig, NODE_ID, mid, hops + 1, cost + link))

def _handle_data(pkt, rssi, snr):
    src, dst, next_hop, mid, ttl, payload = pkt
    if src == NODE_ID:
        return
    if mc.data_seen(src, mid):
        return
    mc.data_mark(src, mid)
    if dst == 0 or dst == NODE_ID:
        ble_notify("MESH_RX:{}|{}|{}|{}|{}|{:.1f}|{}".format(
            src, dst, mid, ttl, rssi, snr, payload))
        _deliver(src, dst, payload)
    if dst == NODE_ID or ttl <= 1:
        return
    if next_hop == 0:
        if random.random() > _relay_prob(rssi):
            print("  -> flood relay skipped (prob)")
            return
        time.sleep(random.uniform(0.05, 0.20))
        _lora_tx_lbt(mc.encode_data(src, dst, 0, mid, ttl - 1, payload))
        print("  -> flood relay")
    elif next_hop == NODE_ID:
        new_nh = mc.route_next_hop(dst)
        if new_nh is None:
            print("  -> no route to N{}, drop".format(dst))
            return
        time.sleep(random.uniform(0.05, 0.15))
        _lora_tx_lbt(mc.encode_data(src, dst, new_nh, mid, ttl - 1, payload))
        print("  -> relay to N{}".format(new_nh))

def _deliver(src, dst, payload):
    print("  v DELIVER from N{}: '{}'".format(src, payload))
    logger.log("RX src={} dst={} '{}'".format(src, dst, payload))
    if payload.startswith("PARROT:"):
        time.sleep(0.15)
        send_data(src, "PONG:{}:{}".format(NODE_ID, payload[7:]))

# ── RX cycle ──────────────────────────────────────────────────────────────────
def rx_cycle():
    global _sf_good_since
    if not lora_ok:
        return
    try:
        result = lora.recv(timeout_en=True, timeout_ms=300)
        if not (result and isinstance(result, tuple) and len(result) >= 2 and result[0]):
            return
        data, _ = result
        rssi = lora.getRSSI()
        snr  = lora.getSNR()
        try:
            s = data.decode('utf-8', 'ignore').strip()
        except Exception:
            return
        if s.startswith("H:"):
            pkt = mc.decode_hello(data)
            if pkt:
                _handle_hello(pkt, rssi, snr)
        elif s.startswith("R:"):
            pkt = mc.decode_route_ad(data)
            if pkt:
                _handle_route_ad(pkt, rssi, snr)
        elif s.startswith("D:"):
            pkt = mc.decode_data(data)
            if pkt:
                _handle_data(pkt, rssi, snr)
        # SF adaptation after fresh SNR data
        if mc.network_sf_check_up():
            _radio_set_sf(mc.network_sf)
            _sf_good_since = None
            ble_notify("MESH_SF:{}".format(mc.network_sf))
            print("SF^ {}".format(mc.network_sf))
        else:
            changed, _sf_good_since = mc.network_sf_check_down(_sf_good_since)
            if changed:
                _radio_set_sf(mc.network_sf)
                ble_notify("MESH_SF:{}".format(mc.network_sf))
                print("SF_ {}".format(mc.network_sf))
    except Exception as e:
        print("RX err: {}".format(e))

# ── BLE command handler ───────────────────────────────────────────────────────
def _handle_ble_cmd(cmd):
    if cmd.startswith("PARROT:"):
        ble_notify("MESH_PARROT:{}".format(cmd[7:]))
    elif cmd.startswith("SEND_MESH:"):
        send_data(0, cmd[10:])
    elif cmd.startswith("SEND_NODE:"):
        rest  = cmd[10:]
        colon = rest.find(":")
        if colon > 0:
            send_data(int(rest[:colon]), rest[colon + 1:])
    elif cmd == "ROUTES":
        for dest, r in mc.route_table.items():
            ble_notify("MESH_ROUTE:{}|{}|{}|{}".format(
                dest, r['next_hop'], r['hops'], r['cost']))
    elif cmd == "NEIGHBORS":
        for nid, nb in mc.neighbor.items():
            ble_notify("MESH_NB:{}|{}|{:.1f}|{}".format(
                nid, nb['rssi'], nb['snr'], nb['sf']))

# ── Periodic maintenance ──────────────────────────────────────────────────────
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
print("Node {}  {} MHz  SF{}".format(NODE_ID, MESH_FREQ, mc.network_sf))
blink(3)

last_hello    = -random.uniform(0, mc.HELLO_INTERVAL * 0.9)
last_route_ad = -random.uniform(0, mc.ROUTE_AD_INTERVAL * 0.9)
last_expire   = 0.0

while True:
    # ── Not connected: advertise, keep mesh running ────────────────────────────
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

    # Send discovery broadcast so all mesh nodes announce themselves
    if lora_ok:
        send_data(0, "DISC:{}".format(NODE_ID))

    time.sleep(1.5)
    ble_notify("MESH_INFO:NODE_ID:{}|SF:{}".format(NODE_ID, mc.network_sf))

    last_ping = time.monotonic()
    ping_n    = 0

    # ── Connected: mesh + BLE ──────────────────────────────────────────────────
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
