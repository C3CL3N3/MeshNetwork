# SPDX-FileCopyrightText: 2026 COMP 4531 HKUST
# SPDX-License-Identifier: MIT
#
# nRF52840 LoRa Mesh Gateway — NODE_ID=1
# Serial commands: <text>  →  broadcast  |  TO:<dst>:<text>  →  unicast
# BLE commands:   SEND_MESH:<text>  |  SEND_NODE:<dst>:<text>  |  ROUTES  |  NEIGHBORS

import sys
sys.stdout.write("=== boot ===\r\n")

import time, random, board, busio, digitalio, supervisor
sys.stdout.write("stdlib ok\r\n")

import mesh_common as mc
from sx1262 import SX1262
sys.stdout.write("mesh+lora lib ok\r\n")

# ── Config ────────────────────────────────────────────────────────────────────
NODE_ID  = 1
GROUP_ID = 13
FREQ     = 912.0
BW       = 125.0
CR       = 5

# ── LED ───────────────────────────────────────────────────────────────────────
led = digitalio.DigitalInOut(board.LED_BLUE)
led.direction = digitalio.Direction.OUTPUT
led.value = True  # OFF (active-low)

def blink(n=1):
    for _ in range(n):
        led.value = False; time.sleep(0.05)
        led.value = True;  time.sleep(0.05)

# ── LoRa init ─────────────────────────────────────────────────────────────────
lora    = None
lora_ok = False
try:
    spi  = busio.SPI(board.D8, board.D10, board.D9)
    lora = SX1262(spi, board.D8, board.D10, board.D9,
                  board.D4, board.D1, board.D2, board.D3, rf_sw=board.D5)
    lora.begin(freq=FREQ, bw=BW, sf=mc.SF, cr=CR,
               useRegulatorLDO=True, tcxoVoltage=0, debug=True)
    lora.recv_start()
    lora_ok = True
    print("lora ok  {} MHz  SF{}".format(FREQ, mc.SF))
    # TX self-test
    lora.send(mc.encode_hello(NODE_ID))
    lora.recv_start()
    print("lora tx test ok")
except Exception as e:
    print("lora fail: {}".format(e))

# ── BLE init (optional) ───────────────────────────────────────────────────────
ble_ok   = False
ble      = None
mesh_svc = None
adv      = None

try:
    import adafruit_ble
    from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
    from adafruit_ble.services import Service
    from adafruit_ble.uuid import VendorUUID
    from adafruit_ble.characteristics import Characteristic

    _h = "{:02x}".format(GROUP_ID)
    class MeshService(Service):
        uuid    = VendorUUID("13172b58-{}40-4150-b42d-22f30b0a0499".format(_h))
        cmd_rx  = Characteristic(
            uuid=VendorUUID("13172b58-{}41-4150-b42d-22f30b0a0499".format(_h)),
            properties=(Characteristic.WRITE | Characteristic.WRITE_NO_RESPONSE),
            max_length=100)
        data_tx = Characteristic(
            uuid=VendorUUID("13172b58-{}42-4150-b42d-22f30b0a0499".format(_h)),
            properties=(Characteristic.READ | Characteristic.NOTIFY),
            max_length=100)

    ble           = adafruit_ble.BLERadio()
    ble.name      = "MESH_G{}".format(GROUP_ID)
    mesh_svc      = MeshService()
    adv           = ProvideServicesAdvertisement(mesh_svc)
    ble_ok        = True
    print("ble ok  {}".format(ble.name))
except Exception as e:
    print("ble fail: {}".format(e))

print("Node {}  lora={}  ble={}".format(NODE_ID, lora_ok, ble_ok))
blink(3)

# ── State ─────────────────────────────────────────────────────────────────────
_msg_id    = 0
_route_mid = 0
_ser_buf   = ''

# ── TX helpers ────────────────────────────────────────────────────────────────
def _tx(pkt):
    if not lora_ok: return
    lora.send(pkt); lora.recv_start()

def _tx_lbt(pkt):
    if not lora_ok: return
    if not lora.send_lbt(pkt, max_tries=3, base_backoff_ms=20):
        print("  lbt drop")
    lora.recv_start()

def _notify(msg):
    if not ble_ok or not ble.connected: return
    try:    mesh_svc.data_tx = msg.encode()[:100]
    except: pass

def _relay_prob(rssi):
    if rssi > -60: return 0.40
    if rssi > -75: return 0.65
    if rssi > -90: return 0.85
    return 0.97

# ── Transmit ──────────────────────────────────────────────────────────────────
def send_hello():
    if not lora_ok: return
    _tx(mc.encode_hello(NODE_ID))
    print("TX H N{}".format(NODE_ID))

def send_route_ad():
    global _route_mid
    if not lora_ok: return
    _route_mid = (_route_mid + 1) % 256
    _tx(mc.encode_route_ad(NODE_ID, NODE_ID, _route_mid, 0))
    print("TX R mid={}".format(_route_mid))

def send_data(dst, payload):
    global _msg_id
    if not lora_ok:
        _notify("MESH_ERR:LORA_FAIL")
        print("tx fail lora_ok=False")
        return False
    _msg_id = (_msg_id + 1) % 256
    mc.data_mark(NODE_ID, _msg_id)
    nh = 0 if dst == 0 else mc.route_next_hop(dst)
    if dst != 0 and nh is None:
        mc.dtn_enqueue(NODE_ID, dst, _msg_id, mc.TTL_DEFAULT, payload)
        _notify("MESH_ERR:NO_ROUTE:{}".format(dst))
        print("tx dtn  no route to N{}".format(dst))
        return False
    pkt = mc.encode_data(NODE_ID, dst, nh, _msg_id, mc.TTL_DEFAULT, payload)
    _tx(pkt)
    _notify("MESH_TX:{}|{}|{}|{}|{}|{}".format(
        NODE_ID, dst, nh, _msg_id, mc.TTL_DEFAULT, payload))
    print("TX D  dst=N{} nh=N{} mid={} '{}'".format(dst, nh or 0, _msg_id, payload))
    return True

# ── RX handlers ───────────────────────────────────────────────────────────────
def _on_hello(src, rssi, snr):
    if src == NODE_ID: return
    mc.neighbor_update(src, snr, rssi)
    _notify("MESH_NB:{}|{}|{:.1f}".format(src, rssi, snr))
    print("RX H  src=N{} rssi={} snr={:.1f}".format(src, rssi, snr))

def _on_route(pkt, rssi, snr):
    orig, fwd, mid, hops = pkt
    if orig == NODE_ID or mc.route_seen(orig, mid): return
    mc.route_mark(orig, mid)
    mc.neighbor_update(fwd, snr, rssi)
    improved = mc.route_update(orig, fwd, hops, mc.neighbor.get(fwd, {}).get('rssi'))
    r = mc.route_table.get(orig, {})
    print("RX R  orig=N{} fwd=N{} mid={} hops={} -> nh=N{} total={} {}".format(
        orig, fwd, mid, hops,
        r.get('next_hop','?'), r.get('hops','?'),
        "[NEW]" if improved else "[known]"))
    if improved:
        _notify("MESH_ROUTE:{}|{}|{}".format(orig, r['next_hop'], r['hops']))
    if hops + 1 < mc.ROUTE_TTL:
        time.sleep(random.uniform(0.02, 0.12))
        _tx_lbt(mc.encode_route_ad(orig, NODE_ID, mid, hops + 1))

def _on_data(pkt, rssi, snr):
    src, dst, nh, mid, ttl, payload = pkt
    if src == NODE_ID or mc.data_seen(src, mid): return
    mc.data_mark(src, mid)
    print("RX D  src=N{} dst=N{} nh=N{} mid={} ttl={} rssi={} '{}'".format(
        src, dst, nh, mid, ttl, rssi, payload))
    if dst == 0 or dst == NODE_ID:
        _notify("MESH_RX:{}|{}|{}|{}|{}|{:.1f}|{}".format(
            src, dst, mid, ttl, rssi, snr, payload))
        _deliver(src, dst, payload)
    if dst == NODE_ID or ttl <= 1: return
    if nh == 0:
        if random.random() > _relay_prob(rssi): return
        time.sleep(random.uniform(0.05, 0.20))
        _tx_lbt(mc.encode_data(src, dst, 0, mid, ttl - 1, payload))
    elif nh == NODE_ID:
        new_nh = mc.route_next_hop(dst)
        if new_nh is None:
            mc.dtn_enqueue(src, dst, mid, ttl - 1, payload); return
        time.sleep(random.uniform(0.05, 0.15))
        _tx_lbt(mc.encode_data(src, dst, new_nh, mid, ttl - 1, payload))

def _deliver(src, dst, payload):
    print("  DELIVER src={} dst={}: '{}'".format(src, dst, payload))
    if payload.startswith("PARROT:"):
        time.sleep(0.15)
        send_data(src, "PONG:{}:{}".format(NODE_ID, payload[7:]))

# ── RX poll ───────────────────────────────────────────────────────────────────
def rx_poll():
    if not lora_ok: return
    try:
        r = lora.recv_poll()
        if r is None: return
        if not r[0]: lora.recv_start(); return
        data, _ = r
        rssi = lora.getRSSI(); snr = lora.getSNR()
        s = data.decode('utf-8', 'ignore').strip()
        if   s.startswith("H:"): src = mc.decode_hello(data);    (src and _on_hello(src, rssi, snr))
        elif s.startswith("R:"): p   = mc.decode_route_ad(data); (p   and _on_route(p,   rssi, snr))
        elif s.startswith("D:"): p   = mc.decode_data(data);     (p   and _on_data(p,    rssi, snr))
        lora.recv_start()
    except Exception as e:
        print("rx err: {}".format(e))
        if lora_ok: lora.recv_start()

# ── Serial input ──────────────────────────────────────────────────────────────
def serial_tick():
    global _ser_buf
    try:
        if not supervisor.runtime.serial_bytes_available: return
        _ser_buf += sys.stdin.read(supervisor.runtime.serial_bytes_available)
        while '\n' in _ser_buf or '\r' in _ser_buf:
            for sep in ('\n', '\r'):
                if sep in _ser_buf:
                    line, _ser_buf = _ser_buf.split(sep, 1); break
            text = line.strip()
            if not text: continue
            if text.startswith("TO:"):
                p = text[3:].split(":", 1)
                if len(p) == 2: send_data(int(p[0]), "[{}] {}".format(NODE_ID, p[1]))
                else: print("usage: TO:<dst>:<msg>")
            else:
                send_data(0, "[{}] {}".format(NODE_ID, text))
    except Exception as e:
        print("serial err: {}".format(e))

# ── BLE command handler ───────────────────────────────────────────────────────
def handle_cmd(cmd):
    if   cmd.startswith("SEND_MESH:"):  send_data(0, "[{}] {}".format(NODE_ID, cmd[10:]))
    elif cmd.startswith("SEND_NODE:"):
        rest = cmd[10:]; i = rest.find(":")
        if i > 0: send_data(int(rest[:i]), "[{}] {}".format(NODE_ID, rest[i+1:]))
    elif cmd.startswith("PARROT:"):     _notify("MESH_PARROT:{}".format(cmd[7:]))
    elif cmd == "ROUTES":
        for dest, r in mc.route_table.items():
            _notify("MESH_ROUTE:{}|{}|{}".format(dest, r['next_hop'], r['hops']))
            time.sleep(0.02)
    elif cmd == "NEIGHBORS":
        for nid, nb in mc.neighbor.items():
            _notify("MESH_NB:{}|{}|{:.1f}".format(nid, nb['rssi'], nb['snr']))
            time.sleep(0.02)

# ── Periodic ──────────────────────────────────────────────────────────────────
_t_hello  = -random.uniform(0, mc.HELLO_INTERVAL    * 0.9)
_t_route  = -random.uniform(0, mc.ROUTE_AD_INTERVAL * 0.9)
_t_expire = 0.0

def periodic(now):
    global _t_hello, _t_route, _t_expire
    if now - _t_hello  >= mc.HELLO_INTERVAL:    _t_hello  = now; send_hello()
    if now - _t_route  >= mc.ROUTE_AD_INTERVAL: _t_route  = now; send_route_ad()
    if now - _t_expire >= 30:
        _t_expire = now; mc.neighbor_expire(); mc.route_expire()
    if lora_ok: mc.dtn_tick(_tx_lbt)

# ── Main ──────────────────────────────────────────────────────────────────────
if not ble_ok:
    print("ble unavailable — running serial+lora only")
    while True:
        periodic(time.monotonic()); rx_poll(); serial_tick(); time.sleep(0.01)

while True:
    ble.start_advertising(adv)
    print("advertising  {}".format(ble.name))

    while not ble.connected:
        led.value = not led.value
        periodic(time.monotonic()); rx_poll(); serial_tick()
        time.sleep(0.1)

    ble.stop_advertising()
    led.value = True
    print("ble connected")
    blink(5)

    if lora_ok: send_data(0, "DISC:{}".format(NODE_ID))
    time.sleep(1.5)
    _notify("MESH_INFO:NODE_ID:{}".format(NODE_ID))

    _t_ping = time.monotonic()
    _ping_n = 0

    while ble.connected:
        now = time.monotonic()
        periodic(now)

        if now - _t_ping >= 5.0:
            _t_ping = now; _ping_n += 1
            _notify("MESH_PING:{}".format(_ping_n))

        try:
            val = mesh_svc.cmd_rx
            if val and len(val) > 1:
                cmd = val.decode('utf-8', 'ignore').strip().replace('\x00', '')
                mesh_svc.cmd_rx = b''
                if cmd:
                    blink(1)
                    print("cmd: {}".format(cmd))
                    handle_cmd(cmd)
        except Exception as e:
            print("ble err: {}".format(e))

        rx_poll(); serial_tick()
        time.sleep(0.001)

    print("ble disconnected")
