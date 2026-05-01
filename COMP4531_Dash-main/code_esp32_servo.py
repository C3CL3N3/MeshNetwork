# SPDX-FileCopyrightText: 2026 Student Lab - COMP 4531 - HKUST
# SPDX-License-Identifier: MIT
#
# LoRa Mesh Relay Node + Bus Servo — XIAO ESP32-S3 + SX1262
# Protocol: H/R/D distance-vector mesh, fixed SF7.
# Servo: Seeed Bus Servo Driver Board (TX=D7, RX=D6) — MG90S PWM
#
# Mesh payload commands:
#   SERVO:<angle>           move servo (0-180°)
#   SERVO:<pin>:<angle>     move servo on specific PWM pin

import time
import random
import busio
import digitalio
import pwmio
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
    rf_sw = digitalio.DigitalInOut(rf_sw_pin)
    rf_sw.direction = digitalio.Direction.OUTPUT
    rf_sw.value = False
    spi  = busio.SPI(sck_pin, mosi_pin, miso_pin)
    lora = SX1262(spi, sck_pin, mosi_pin, miso_pin,
                  nss_pin, dio1_pin, rst_pin, busy_pin)
    lora.begin(freq=MESH_FREQ, bw=BW, sf=mc.SF, cr=CR,
               useRegulatorLDO=True, tcxoVoltage=1.8, power=22)
    print("Node {}  {} MHz  SF{}  TTL={}".format(NODE_ID, MESH_FREQ, mc.SF, mc.TTL_DEFAULT))
except Exception as e:
    print("LoRa FAIL: {}".format(e))
    raise

# ── Servo (MG90S — standard PWM, 50 Hz, 500–2500 µs) ─────────────────────────
_SERVO_PIN  = board.D7   # signal wire from Bus Servo Driver Board
_PWM_FREQ   = 50
_MIN_US     = 500
_MAX_US     = 2500
_PERIOD_US  = 1_000_000 // _PWM_FREQ   # 20000

_servo_pwm = pwmio.PWMOut(_SERVO_PIN, frequency=_PWM_FREQ, duty_cycle=0)

def _servo_angle(degrees):
    degrees = max(0, min(180, float(degrees)))
    us      = _MIN_US + (degrees / 180.0) * (_MAX_US - _MIN_US)
    _servo_pwm.duty_cycle = int(us / _PERIOD_US * 65535)
    print("  servo angle={:.1f}".format(degrees))

def _servo_cmd(payload):
    parts = payload[6:].split(":")
    try:
        if len(parts) == 1:
            _servo_angle(parts[0])
        else:
            _servo_angle(parts[1])   # ignore pin field for now
    except Exception as e:
        print("  servo err: {}".format(e))

# ── Node state ────────────────────────────────────────────────────────────────
my_msg_id    = 0
my_route_mid = 0
_serial_buf  = ''

# ── TX helpers ────────────────────────────────────────────────────────────────
def _lora_tx(pkt_bytes):
    rf_sw.value = True
    lora.send(pkt_bytes)
    rf_sw.value = False

def _lora_tx_lbt(pkt_bytes):
    for attempt in range(5):
        result = lora.recv(timeout_en=True, timeout_ms=25)
        if not (result and isinstance(result, tuple) and result[0]):
            rf_sw.value = True
            lora.send(pkt_bytes)
            rf_sw.value = False
            return
        time.sleep(0.06 * (2 ** attempt) + random.uniform(0, 0.04))
    print("  LBT: dropped")

def _relay_prob(rssi):
    if rssi > -60:  return 0.40
    if rssi > -75:  return 0.65
    if rssi > -90:  return 0.85
    return 0.97

# ── Transmit ──────────────────────────────────────────────────────────────────
def send_hello():
    _lora_tx(mc.encode_hello(NODE_ID))

def send_route_ad_self():
    global my_route_mid
    my_route_mid = (my_route_mid + 1) % 256
    _lora_tx(mc.encode_route_ad(NODE_ID, NODE_ID, my_route_mid, 0))

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
    print("H  N{} rssi={} snr={:.1f}".format(src, rssi, snr))

def _handle_route_ad(pkt, rssi, snr):
    orig, fwd, mid, hops = pkt
    if orig == NODE_ID or mc.route_seen(orig, mid):
        return
    mc.route_mark(orig, mid)
    mc.neighbor_update(fwd, snr, rssi)
    improved = mc.route_update(orig, fwd, hops)
    print("R  orig={} fwd={} hops={}{}".format(orig, fwd, hops, " *" if improved else ""))
    if hops + 1 < mc.ROUTE_TTL:
        time.sleep(random.uniform(0.02, 0.12))
        _lora_tx_lbt(mc.encode_route_ad(orig, NODE_ID, mid, hops + 1))

def _handle_data(pkt, rssi, snr):
    src, dst, next_hop, mid, ttl, payload = pkt
    if src == NODE_ID or mc.data_seen(src, mid):
        return
    mc.data_mark(src, mid)
    print("D  src={} dst={} ttl={} rssi={} '{}'".format(src, dst, ttl, rssi, payload))
    if dst == 0 or dst == NODE_ID:
        _deliver(src, payload)
    if dst == NODE_ID or ttl <= 1:
        return
    if next_hop == 0:
        if random.random() > _relay_prob(rssi):
            return
        time.sleep(random.uniform(0.05, 0.20))
        _lora_tx_lbt(mc.encode_data(src, dst, 0, mid, ttl - 1, payload))
        return
    if next_hop != NODE_ID:
        return
    new_nh = mc.route_next_hop(dst)
    if new_nh is None:
        return
    time.sleep(random.uniform(0.05, 0.15))
    _lora_tx_lbt(mc.encode_data(src, dst, new_nh, mid, ttl - 1, payload))

def _deliver(src, payload):
    print("  DELIVER N{}: '{}'".format(src, payload))
    if payload.startswith("SERVO:"):
        _servo_cmd(payload)
    elif payload.startswith("PARROT:"):
        time.sleep(0.15)
        send_data(src, "PONG:{}:{}".format(NODE_ID, payload[7:]))

# ── RX cycle ──────────────────────────────────────────────────────────────────
def rx_cycle():
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

# ── Main ──────────────────────────────────────────────────────────────────────
print("Mesh servo node running — Node {}".format(NODE_ID))
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
                            send_data(int(parts[0]), parts[1])
                        else:
                            print("Usage: TO:<dst>:<message>")
                    else:
                        send_data(0, text)
    except Exception as e:
        print("Serial err: {}".format(e))

    rx_cycle()
    time.sleep(0.01)
