# SPDX-FileCopyrightText: 2026 Student Lab - COMP 4531 - HKUST
# SPDX-License-Identifier: MIT
#
# LoRa Mesh Relay Node — XIAO ESP32-S3 + SX1262
# Protocol: H/R/D distance-vector mesh, fixed SF7.
# Serial commands:
#   <text>          → broadcast DATA (dst=0)
#   TO:<dst>:<text> → unicast DATA to node dst

import time
import random
import busio
import microcontroller
import board
import supervisor
import sys
import mesh_common as mc
from sx1262 import SX1262

# ── Identity ──────────────────────────────────────────────────────────────────
NODE_ID = 2  # unique per board (1–255); 1 reserved for nRF gateway

# ── LoRa parameters ───────────────────────────────────────────────────────────
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
    spi  = busio.SPI(sck_pin, mosi_pin, miso_pin)
    lora = SX1262(spi, sck_pin, mosi_pin, miso_pin,
                  nss_pin, dio1_pin, rst_pin, busy_pin, rf_sw=rf_sw_pin)
    lora.begin(freq=MESH_FREQ, bw=BW, sf=mc.SF, cr=CR,
               useRegulatorLDO=True, tcxoVoltage=1.8, power=22)
    lora.recv_start()
    print("Node {}  {} MHz  SF{}  TTL={}".format(NODE_ID, MESH_FREQ, mc.SF, mc.TTL_DEFAULT))
except Exception as e:
    print("LoRa FAIL: {}".format(e))
    raise

# ── Node state ────────────────────────────────────────────────────────────────
my_msg_id    = 0
my_route_mid = 0
_serial_buf  = ''

# ── TX helpers ────────────────────────────────────────────────────────────────
def _lora_tx(pkt_bytes):
    lora.send(pkt_bytes)
    lora.recv_start()

def _lora_tx_lbt(pkt_bytes):
    if not lora.send_lbt(pkt_bytes, max_tries=3, base_backoff_ms=20):
        print("  LBT: dropped")
    lora.recv_start()

def _relay_prob(rssi):
    if rssi > -60:  return 0.40
    if rssi > -75:  return 0.65
    if rssi > -90:  return 0.85
    return 0.97

# ── Transmit ──────────────────────────────────────────────────────────────────
def send_hello():
    _lora_tx(mc.encode_hello(NODE_ID))
    print("TX H N{}".format(NODE_ID))

def send_route_ad_self():
    global my_route_mid
    my_route_mid = (my_route_mid + 1) % 256
    _lora_tx(mc.encode_route_ad(NODE_ID, NODE_ID, my_route_mid, 0))
    print("TX R mid={}".format(my_route_mid))

def send_data(dst, payload):
    global my_msg_id
    my_msg_id = (my_msg_id + 1) % 256
    mc.data_mark(NODE_ID, my_msg_id)
    nh = 0 if dst == 0 else mc.route_next_hop(dst)
    if dst != 0 and nh is None:
        print("No route to N{}".format(dst))
        return False
    _lora_tx(mc.encode_data(NODE_ID, dst, nh, my_msg_id, mc.TTL_DEFAULT, payload))
    print("TX D dst={} nh={} '{}'".format(dst, nh, payload))
    return True

# ── Receive handlers ──────────────────────────────────────────────────────────
def _handle_hello(src, rssi, snr):
    if src == NODE_ID:
        return
    mc.neighbor_update(src, snr, rssi)
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
        return
    if next_hop != NODE_ID:
        return
    new_nh = mc.route_next_hop(dst)
    if new_nh is None:
        mc.dtn_enqueue(src, dst, mid, ttl - 1, payload)
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

# ── RX poll (non-blocking) ────────────────────────────────────────────────────
def rx_poll():
    try:
        result = lora.recv_poll()
        if result is None:
            return
        if not (result[0]):
            lora.recv_start()
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
        lora.recv_start()
    except Exception as e:
        print("RX err: {}".format(e))
        lora.recv_start()

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
        dead_nb = mc.neighbor_expire()
        dead_rt = mc.route_expire()
        if dead_nb: print("Expired nb: {}".format(dead_nb))
        if dead_rt: print("Expired rt: {}".format(dead_rt))
    mc.dtn_tick(_lora_tx_lbt)

# ── Main ──────────────────────────────────────────────────────────────────────
print("Mesh relay running — Node {}".format(NODE_ID))
last_hello    = -random.uniform(0, mc.HELLO_INTERVAL * 0.9)
last_route_ad = -random.uniform(0, mc.ROUTE_AD_INTERVAL * 0.9)
last_expire   = 0.0

while True:
    now = time.monotonic()
    _periodic(now)

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
                            send_data(int(parts[0]), "[{}] {}".format(NODE_ID, parts[1]))
                        else:
                            print("Usage: TO:<dst>:<message>")
                    else:
                        send_data(0, "[{}] {}".format(NODE_ID, text))
    except Exception as e:
        print("Serial err: {}".format(e))

    rx_poll()
    time.sleep(0.001)
