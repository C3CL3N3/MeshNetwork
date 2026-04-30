# SPDX-FileCopyrightText: 2026 Student Lab - COMP 4531 - HKUST
# SPDX-License-Identifier: MIT
#
# LoRa Mesh Relay Node — XIAO ESP32-S3 + SX1262
# Protocol: H/R/D three-packet distance-vector mesh with adaptive SF.
# Serial commands:
#   <text>              → broadcast DATA (dst=0)
#   TO:<dst>:<text>     → unicast DATA to node dst
#
# Mesh payload commands (received by this node):
#   SERVO:<angle>           move servo ID 1 to angle (degrees, 0-300)
#   SERVO:<id>:<angle>      move specific servo ID
#   SERVO:<id>:<angle>:<ms> move with time budget in ms

import time
import random
import busio
import digitalio
import microcontroller
import board
import supervisor
import sys
import mesh_common as mc
from sx1262 import SX1262
import logger

# ── Identity ──────────────────────────────────────────────────────────────────
NODE_ID = 2  # unique per physical board (1–255); 1 is reserved for nRF gateway

# ── LoRa hardware parameters ──────────────────────────────────────────────────
MESH_FREQ = 912.0
BW        = 125.0
CR        = 5

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
    lora.begin(freq=MESH_FREQ, bw=BW, sf=mc.network_sf, cr=CR,
               useRegulatorLDO=True, tcxoVoltage=1.8, power=22)
    print("Node {}  {} MHz  SF{}  TTL={}".format(NODE_ID, MESH_FREQ, mc.network_sf, mc.TTL_DEFAULT))
    logger.init()
except Exception as e:
    print("LoRa FAIL: {}".format(e))
    raise

# ── Node state ────────────────────────────────────────────────────────────────
my_msg_id      = 0
my_route_mid   = 0
_serial_buf    = ''
_active_sf     = mc.network_sf
_sf_good_since = None

# ── Radio SF management ───────────────────────────────────────────────────────
def _radio_set_sf(sf):
    global _active_sf
    if sf == _active_sf:
        return
    lora.begin(freq=MESH_FREQ, bw=BW, sf=sf, cr=CR,
               useRegulatorLDO=True, tcxoVoltage=1.8, power=22)
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
    """RSSI-weighted relay probability — strong signal → many neighbours
    already relayed → lower chance needed."""
    if rssi > -60:  return 0.40
    if rssi > -75:  return 0.65
    if rssi > -90:  return 0.85
    return 0.97

# ── Transmit functions ────────────────────────────────────────────────────────
def send_hello():
    _lora_tx(mc.encode_hello(NODE_ID, mc.network_sf))
    print("TX H sf={}".format(mc.network_sf))

def send_route_ad_self():
    global my_route_mid
    my_route_mid = (my_route_mid + 1) % 256
    # Originating node: fwd=self, hops=0, cost=0
    _lora_tx(mc.encode_route_ad(NODE_ID, NODE_ID, my_route_mid, 0, 0))
    print("TX R self mid={}".format(my_route_mid))

def send_data(dst, payload):
    """Originate a DATA packet. dst=0 for broadcast. Returns True on success."""
    global my_msg_id
    my_msg_id = (my_msg_id + 1) % 256
    mc.data_mark(NODE_ID, my_msg_id)
    if dst == 0:
        nh = 0
    else:
        nh = mc.route_next_hop(dst)
        if nh is None:
            print("No route to N{}".format(dst))
            return False
    _lora_tx(mc.encode_data(NODE_ID, dst, nh, my_msg_id, mc.TTL_DEFAULT, payload))
    print("TX D dst={} nh={} mid={} '{}'".format(dst, nh, my_msg_id, payload))
    return True

# ── Receive handlers ──────────────────────────────────────────────────────────
def _handle_hello(pkt, rssi, snr):
    src, src_sf = pkt
    if src == NODE_ID:
        return
    old_sf, new_sf = mc.neighbor_update(src, snr, rssi)
    tag = "  ASF: SF{}->SF{}".format(old_sf, new_sf) if new_sf != old_sf else ""
    print("H  N{} sf={} rssi={} snr={:.1f}{}".format(src, src_sf, rssi, snr, tag))

def _handle_route_ad(pkt, rssi, snr):
    orig, fwd, mid, hops, cost = pkt
    if orig == NODE_ID:
        return
    if mc.route_seen(orig, mid):
        return
    mc.route_mark(orig, mid)
    # fwd is the immediate transmitter — update its link metrics
    mc.neighbor_update(fwd, snr, rssi)
    improved = mc.route_update(orig, fwd, hops, cost)
    print("R  orig={} fwd={} hops={} cost={}{}".format(
        orig, fwd, hops, cost, " *" if improved else ""))
    # Relay within TTL: forward with NODE_ID as new fwd, incremented hops+cost
    if hops + 1 < mc.ROUTE_TTL:
        nb = mc.neighbor.get(fwd)
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
    print("D  src={} dst={} nh={} ttl={} rssi={} '{}'".format(
        src, dst, next_hop, ttl, rssi, payload))
    # Deliver locally if broadcast or addressed to this node
    if dst == 0 or dst == NODE_ID:
        _deliver(src, dst, payload)
    if dst == NODE_ID or ttl <= 1:
        return
    # Broadcast: probabilistic relay weighted by RSSI
    if next_hop == 0:
        if random.random() > _relay_prob(rssi):
            print("  -> flood relay skipped (prob)")
            return
        time.sleep(random.uniform(0.05, 0.20))
        _lora_tx_lbt(mc.encode_data(src, dst, 0, mid, ttl - 1, payload))
        print("  -> flood relay")
        return
    # Unicast: only the designated next_hop relays
    if next_hop != NODE_ID:
        return
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
    """Non-blocking receive + dispatch + SF adaptation check."""
    global _sf_good_since
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
        # SF adaptation — checked after every received packet (fresh SNR data)
        if mc.network_sf_check_up():
            _radio_set_sf(mc.network_sf)
            _sf_good_since = None
            print("SF^ {}".format(mc.network_sf))
        else:
            changed, _sf_good_since = mc.network_sf_check_down(_sf_good_since)
            if changed:
                _radio_set_sf(mc.network_sf)
                print("SF_ {}".format(mc.network_sf))
    except Exception as e:
        print("RX err: {}".format(e))

# ── Periodic maintenance ──────────────────────────────────────────────────────
def _periodic(now):
    """Fire timed tasks. Call from main loop with time.monotonic()."""
    global last_hello, last_route_ad, last_expire
    if now - last_hello >= mc.HELLO_INTERVAL:
        last_hello = now
        send_hello()
    if now - last_route_ad >= mc.ROUTE_AD_INTERVAL:
        last_route_ad = now
        send_route_ad_self()
    if now - last_expire >= 30:
        last_expire = now
        dead_nb = mc.neighbor_expire()
        dead_rt = mc.route_expire()
        if dead_nb:
            print("Expired neighbors: {}".format(dead_nb))
        if dead_rt:
            print("Expired routes: {}".format(dead_rt))

# ── Main ──────────────────────────────────────────────────────────────────────
print("Mesh relay running — Node {}".format(NODE_ID))
last_hello    = -random.uniform(0, mc.HELLO_INTERVAL * 0.9)
last_route_ad = -random.uniform(0, mc.ROUTE_AD_INTERVAL * 0.9)
last_expire   = 0.0

while True:
    now = time.monotonic()
    _periodic(now)

    # Serial input: broadcast or unicast
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
                            send_data(int(parts[0]), parts[1])
                        else:
                            print("Usage: TO:<dst>:<message>")
                    else:
                        send_data(0, text)
    except Exception as e:
        print("Serial err: {}".format(e))

    rx_cycle()
    time.sleep(0.01)
