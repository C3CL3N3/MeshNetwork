# SPDX-License-Identifier: MIT
# mesh_core.py — single-file mesh firmware library (flat root, no subdirectories)

import random
import time
import sys

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG (from software/config.py)
# ═══════════════════════════════════════════════════════════════════════════════

GROUP_ID   = 13
NODE_ID    = 1
BOARD_PROFILE = "esp32_sx1262"
ROLE       = "R"
ALLOW_EXTERNAL_COMMANDS = (ROLE == "C")
CONTROLLER_ID  = 1            # node ID of the controller/gateway that aggregates topology
REPORT_TOPOLOGY = True         # needed for graph viz + topology routing fallback
SF_AUTO_ENABLED = False        # FROZEN: future auto-SF code is disabled in this build
SF_SCAN_TIMEOUT_S = 8.0       # seconds to listen at each SF during boot scan
SF_SCAN_ENABLED = False        # FROZEN: no SF scan/sweep while the network is SF7-only

FREQ_BASE_MHZ   = 900.0
FREQ_STEP_MHZ   = 1.0
LORA_BW_KHZ     = 125.0
LORA_SF         = 7
LORA_CR         = 5
LORA_TX_POWER   = 22

# ── Adaptive SF thresholds ───────────────────────────────────────────────────
# Based on Semtech SX1262 demodulation floors at 125 kHz BW + 3 dB margin.
# Escalation triggers when SNR drops near the floor; de-escalation requires
# sustained margin above the next SF's floor.
# Demod floors: SF7=-7.5  SF8=-10  SF9=-12.5  SF10=-15  SF11=-17.5  SF12=-20 dB
SF_HOLD = {7: -7.5, 8: -10.0, 9: -12.5, 10: -15.0, 11: -17.5, 12: -99.0}
# SNR must exceed these ceilings for ALL neighbors before downgrading
SF_DOWN = {8: 5.0, 9: 2.5, 10: 0.0, 11: -2.5, 12: -5.0}
# RSSI floors: if any link's RSSI drops below, upgrade SF (secondary trigger)
SF_RSSI_HOLD = {7: -115, 8: -118, 9: -121, 10: -124, 11: -127, 12: -130}
SF_DOWN_HOLD_S = 60.0
SF_UP_CONSECUTIVE = 2  # consecutive bad readings required before escalating

# ── Mutable runtime config (dict avoids `global` in methods — CircuitPython compat) ──
_cfg = {
    'report_topo':    REPORT_TOPOLOGY,
    'topo_interval':  0,        # 0 = mode-based; >0 = override seconds
    'sf_mode':        "7",     # FROZEN: SF7-only until base connectivity is solid
    'network_sf':     LORA_SF,  # current operating SF
    'sf_good_since':  None,     # downgrade hysteresis timestamp
    'sf_bad_count':   0,        # consecutive bad-SNR readings for escalation
    'route_mode':     "reliable",
}

TTL_DEFAULT       = 6
ROUTE_TTL         = 5
HELLO_INTERVAL_S  = 10.0
ROUTE_AD_INTERVAL_S = 30.0
EXPIRE_INTERVAL_S = 30.0
NEIGHBOR_EXPIRE_S = 120.0
ROUTE_EXPIRE_S    = 90.0
TOPOLOGY_EXPIRE_S = 30.0

CACHE_SIZE    = 60
DTN_TTL_S     = 30.0
DTN_RETRY_S   = 3.0
DTN_QUEUE_MAX = 16

ROUTE_SWITCH_MARGIN  = 0
ROUTE_RSSI_MARGIN_DB = 4
ROUTE_MODE = "reliable"  # reliable | fastest
ROUTE_RELIABLE_HOP_PENALTY_DB = 3
ROUTE_RELIABLE_SWITCH_MARGIN_DB = 8

RELAY_JITTER_MIN_S = 0.05
RELAY_JITTER_MAX_S = 0.20
ROUTE_JITTER_MIN_S = 0.02
ROUTE_JITTER_MAX_S = 0.12

CONTROL_PREFIXES = ("CMD:", "ENDPOINT:", "SERVO:", "CAPS?", "PING",
                     "F", "B", "L", "R", "S", "+", "-",
                     "FORWARD", "BACKWARD", "LEFT", "RIGHT", "STOP",
                     "H:", "V:", "HEADING:", "SPEED:", "FWD:", "BACK:")

ENDPOINT_ACTUATOR        = "pwm_servo"
ENDPOINT_ENABLE_PWM_SERVO = True
ENDPOINT_SERVO_PIN       = "D7"
ENDPOINT_SERVO_MIN_ANGLE = 0
ENDPOINT_SERVO_MAX_ANGLE = 180
ENDPOINT_SERVO_MIN_US    = 500
ENDPOINT_SERVO_MAX_US    = 2500
ENDPOINT_DEBUG_TARGET_NODE = 1
ENDPOINT_DEBUG_INTERVAL_S  = 10.0

LOG_TO_FILE = False             # set True to write mesh_log.csv on CIRCUITPY
LOG_FILE_MAX_LINES = 500        # rotate when exceeded

BLE_GROUP_ID      = GROUP_ID
BLE_NAME_PREFIX   = "MESH_G"
BLE_NOTIFY_MAX_LEN = 100

# ── Adaptive check intervals ──────────────────────────────────────────────────
MODE_BOOT   = 0
MODE_ACTIVE = 1
MODE_NORMAL = 2
MODE_QUIET  = 3

MODE_INTERVALS = {
    # (hello_s, route_s, topo_max_s) — topology is event-driven, topo_max is fallback
    MODE_BOOT:   (5,   5,   300),
    MODE_ACTIVE: (10,  10,  300),
    MODE_NORMAL: (10,  30,  300),
    MODE_QUIET:  (30,  60,  600),
}

MGMT_TX_GAP_S      = 0.75  # minimum gap between periodic H/R/T packets
ROUTE_TX_OFFSET_S  = 1.0   # stagger route ads after hello
TOPO_TX_OFFSET_S   = 2.0   # stagger topology after hello/route
TOPO_CHANGE_RSSI_DB = 8    # RSSI change that triggers an immediate topology report
TOPO_MIN_REPORT_GAP_S = 20 # suppress noisy topology repeats during RF jitter
BOOT_DURATION      = 60    # seconds in BOOT before transitioning to NORMAL
STABLE_CHECKS      = 4     # consecutive stable checks before downgrading mode
RSSI_CHANGE_THRESH = 6     # dB change that counts as a topology change

# ═══════════════════════════════════════════════════════════════════════════════
# PROTOCOL PACKETS (from software/protocol/packets.py)
# ═══════════════════════════════════════════════════════════════════════════════

class PacketDecodeError(ValueError):
    pass

class HelloPacket:
    __slots__ = ("src", "role", "sf")
    def __init__(self, src, role="?", sf=7):
        self.src = int(src); self.role = str(role) if role else "?"
        self.sf = int(sf) if sf else LORA_SF

class RouteAdPacket:
    __slots__ = ("orig", "fwd", "mid", "hops", "path_rssi", "path_snr")
    def __init__(self, orig, fwd, mid, hops, path_rssi=None, path_snr=None):
        self.orig = int(orig); self.fwd = int(fwd)
        self.mid  = int(mid) & 0xFF; self.hops = int(hops)
        self.path_rssi = int(path_rssi) if path_rssi is not None else None
        self.path_snr = float(path_snr) if path_snr is not None else None

class DataPacket:
    __slots__ = ("src", "dst", "next_hop", "mid", "ttl", "payload")
    def __init__(self, src, dst, next_hop, mid, ttl, payload):
        self.src = int(src); self.dst = int(dst)
        self.next_hop = int(next_hop); self.mid = int(mid) & 0xFF
        self.ttl = int(ttl); self.payload = str(payload)

class TopologyPacket:
    __slots__ = ("src", "seq", "neighbors")
    def __init__(self, src, seq, neighbors):
        self.src = int(src); self.seq = int(seq) & 0xFF
        self.neighbors = dict(neighbors)  # {node_id: (rssi, snr)} or legacy {node_id: rssi}

class OrientationPacket:
    __slots__ = ("src", "dst", "seq", "routes")
    def __init__(self, src, dst, seq, routes):
        self.src = int(src); self.dst = int(dst)
        self.seq = int(seq) & 0xFF
        self.routes = dict(routes)  # {dest: hops}

class PacketCodec:
    def encode_hello(self, src, role="?", sf=7):
        return "H:{0}:{1}:{2}".format(int(src), role or "?", int(sf)).encode("utf-8")

    def encode_route_ad(self, orig, fwd, mid, hops, path_rssi=None, path_snr=None):
        base = "R:{0}:{1}:{2}:{3}".format(
            int(orig), int(fwd), int(mid) & 0xFF, int(hops))
        if path_rssi is not None:
            base += ":{0}:{1:.1f}".format(int(path_rssi), float(path_snr or 0.0))
        return base.encode("utf-8")

    def encode_data(self, src, dst, next_hop, mid, ttl, payload):
        return "D:{0}:{1}:{2}:{3}:{4}:{5}".format(
            int(src), int(dst), int(next_hop), int(mid) & 0xFF,
            int(ttl), str(payload)).encode("utf-8")

    def encode_topology(self, src, seq, neighbors):
        # Returns a string payload for use inside a D packet
        # Format: T:<src>:<seq>:<nid1>,<rssi1>,<snr1>;<nid2>,<rssi2>,<snr2>;...
        header = "T:{0}:{1}".format(int(src), int(seq) & 0xFF)
        parts = []
        for n, val in sorted(neighbors.items()):
            if isinstance(val, tuple):
                rssi, snr = val
            else:
                rssi, snr = val, 0.0
            parts.append("{0},{1},{2:.1f}".format(int(n), int(rssi), float(snr)))
        return header + ":" + ";".join(parts) if parts else header + ":*"

    def encode_orientation(self, src, dst, seq, routes):
        # Returns a string payload for use inside a D packet
        # Format: O:<src>:<dst>:<seq>:<dest1>,<hops1>;<dest2>,<hops2>;...
        header = "O:{0}:{1}:{2}".format(int(src), int(dst), int(seq) & 0xFF)
        entries = ";".join("{0},{1}".format(int(d), int(h)) for d, h in sorted(routes.items()))
        return header + ":" + entries if entries else header + ":*"

    def _decode_topology(self, payload):
        # Decode a T: payload string extracted from a D packet
        # Format: nid,rssi,snr  or legacy: nid,rssi
        rest = payload[2:].split(":", 2)
        if len(rest) < 2: raise PacketDecodeError("bad TOPOLOGY")
        src = int(rest[0]); seq = int(rest[1])
        neighbors = {}
        if len(rest) > 2 and rest[2] != "*":
            for item in rest[2].split(";"):
                item = item.strip()
                if not item: continue
                parts = item.split(",")
                nid = int(parts[0])
                rssi = int(parts[1])
                snr = float(parts[2]) if len(parts) > 2 else 0.0
                neighbors[int(nid)] = (rssi, snr)
        return TopologyPacket(src, seq, neighbors)

    def _decode_orientation(self, payload):
        # Decode an O: payload string extracted from a D packet
        rest = payload[2:].split(":", 3)
        if len(rest) < 3: raise PacketDecodeError("bad ORIENTATION")
        src = int(rest[0]); dst = int(rest[1]); seq = int(rest[2])
        routes = {}
        if len(rest) > 3:
            for item in rest[3].split(";"):
                item = item.strip()
                if not item: continue
                dest, hops = item.split(",")
                routes[int(dest)] = int(hops)
        return OrientationPacket(src, dst, seq, routes)

    def decode(self, raw):
        if raw is None: return None
        if isinstance(raw, str): text = raw.strip()
        else:
            try: text = bytes(raw).decode("utf-8", "ignore").strip()
            except Exception as e: raise PacketDecodeError("not text") from e
        if not text: return None
        if text.startswith("H:"): return self._decode_hello(text)
        if text.startswith("R:"): return self._decode_route_ad(text)
        if text.startswith("D:"): return self._decode_data(text)
        return None

    def _decode_hello(self, text):
        parts = text[2:].split(":")
        if len(parts) < 1: raise PacketDecodeError("bad HELLO")
        role = parts[1] if len(parts) > 1 else "?"
        sf = int(parts[2]) if len(parts) > 2 else LORA_SF
        return HelloPacket(int(parts[0]), role=role, sf=sf)

    def _decode_route_ad(self, text):
        parts = text[2:].split(":")
        if len(parts) not in (4, 6): raise PacketDecodeError("bad ROUTE_AD")
        path_rssi = int(parts[4]) if len(parts) == 6 else None
        path_snr = float(parts[5]) if len(parts) == 6 else None
        return RouteAdPacket(int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]),
                             path_rssi=path_rssi, path_snr=path_snr)

    def _decode_data(self, text):
        parts = text[2:].split(":", 5)
        if len(parts) != 6: raise PacketDecodeError("bad DATA")
        return DataPacket(int(parts[0]), int(parts[1]), int(parts[2]),
                          int(parts[3]), int(parts[4]), parts[5])

# ═══════════════════════════════════════════════════════════════════════════════
# CACHE (from software/network/cache.py)
# ═══════════════════════════════════════════════════════════════════════════════

class DedupCache:
    def __init__(self, capacity=60):
        self.capacity = int(capacity); self._items = []

    def seen(self, key): return key in self._items

    def mark(self, key):
        self._items.append(key)
        while len(self._items) > self.capacity: self._items.pop(0)

# ═══════════════════════════════════════════════════════════════════════════════
# NEIGHBOR TABLE (from software/network/neighbor_table.py)
# ═══════════════════════════════════════════════════════════════════════════════

class NeighborTable:
    def __init__(self, expire_s=120.0):
        self.expire_s = float(expire_s); self._items = {}

    def update(self, node_id, rssi=None, snr=None, role=None, now_s=0.0):
        node_id = int(node_id)
        prev = self._items.get(node_id, {})
        self._items[node_id] = {
            "rssi": int(rssi) if rssi is not None else prev.get("rssi", -999),
            "snr":  float(snr) if snr is not None else prev.get("snr", 0.0),
            "role": str(role) if role else prev.get("role", "?"),
            "seen": float(now_s),
        }
        return self._items[node_id]

    def get(self, node_id): return self._items.get(int(node_id))

    def has(self, node_id): return int(node_id) in self._items

    def expire(self, now_s):
        dead = []
        for nid, item in list(self._items.items()):
            if float(now_s) - item["seen"] > self.expire_s:
                dead.append(nid); del self._items[nid]
        return dead

    def items(self): return self._items.items()

    def snapshot(self):
        """Return {node_id: (rssi, snr)} for mode-transition diff and topology encoding."""
        return {nid: (item["rssi"], item["snr"]) for nid, item in self._items.items()}

    def changed_since(self, prev_snapshot, rssi_thresh=6):
        """Return True if the neighbor set or RSSI values changed significantly."""
        cur = self.snapshot()
        if set(cur.keys()) != set(prev_snapshot.keys()):
            return True
        for nid in cur:
            cur_rssi = cur[nid][0] if isinstance(cur[nid], tuple) else cur[nid]
            prev_val = prev_snapshot.get(nid, -999)
            prev_rssi = prev_val[0] if isinstance(prev_val, tuple) else prev_val
            if abs(cur_rssi - prev_rssi) > int(rssi_thresh):
                return True
        return False

# ═══════════════════════════════════════════════════════════════════════════════
# ROUTE TABLE (from software/network/route_table.py)
# ═══════════════════════════════════════════════════════════════════════════════

class RouteTable:
    MODE_FASTEST = "fastest"
    MODE_RELIABLE = "reliable"

    def __init__(self, expire_s=90.0, switch_margin=0, rssi_margin_db=4,
                 mode="fastest", reliable_hop_penalty_db=3,
                 reliable_switch_margin_db=8):
        self.expire_s = float(expire_s)
        self.switch_margin = int(switch_margin)
        self.rssi_margin_db = int(rssi_margin_db)
        self.mode = self._normalize_mode(mode)
        self.reliable_hop_penalty_db = int(reliable_hop_penalty_db)
        self.reliable_switch_margin_db = int(reliable_switch_margin_db)
        self._items = {}

    def _normalize_mode(self, mode):
        mode = str(mode or self.MODE_FASTEST).strip().lower()
        if mode not in (self.MODE_FASTEST, self.MODE_RELIABLE):
            return self.MODE_FASTEST
        return mode

    def set_mode(self, mode):
        self.mode = self._normalize_mode(mode)

    def _path_rssi(self, link_rssi, advertised_path_rssi):
        link = int(link_rssi) if link_rssi is not None else -999
        path = int(advertised_path_rssi) if advertised_path_rssi is not None else link
        if path <= -999: return link
        if link <= -999: return path
        return min(link, path)

    def _path_snr(self, link_snr, advertised_path_snr):
        link = float(link_snr) if link_snr is not None else None
        path = float(advertised_path_snr) if advertised_path_snr is not None else link
        if link is None: return path if path is not None else 0.0
        if path is None: return link
        return min(link, path)

    def _reliable_score(self, hops, path_rssi, path_snr):
        snr_bonus = max(-20.0, min(20.0, float(path_snr))) * 2.0
        hop_penalty = max(0, int(hops) - 1) * self.reliable_hop_penalty_db
        return float(path_rssi) + snr_bonus - hop_penalty

    def update(self, dest, next_hop, advertised_hops, link_rssi=None,
               link_snr=None, path_rssi=None, path_snr=None, now_s=0.0):
        dest = int(dest); next_hop = int(next_hop)
        total_hops = int(advertised_hops) + 1
        rssi = int(link_rssi) if link_rssi is not None else -999
        snr = float(link_snr) if link_snr is not None else 0.0
        bottleneck_rssi = self._path_rssi(link_rssi, path_rssi)
        bottleneck_snr = self._path_snr(link_snr, path_snr)
        score = self._reliable_score(total_hops, bottleneck_rssi, bottleneck_snr)
        cur = self._items.get(dest)
        improved = False
        if cur is None: improved = True
        elif self.mode == self.MODE_RELIABLE:
            if score >= cur.get("score", -9999) + self.reliable_switch_margin_db:
                improved = True
            elif total_hops < cur["hops"] and score >= cur.get("score", -9999) - self.reliable_switch_margin_db:
                improved = True
        else:
            if total_hops < cur["hops"] - self.switch_margin: improved = True
            elif total_hops == cur["hops"] and bottleneck_rssi >= cur["path_rssi"] + self.rssi_margin_db:
                improved = True
        if improved:
            self._items[dest] = {"next_hop": next_hop, "hops": total_hops,
                                 "link_rssi": rssi, "link_snr": snr,
                                 "path_rssi": bottleneck_rssi,
                                 "path_snr": bottleneck_snr,
                                 "score": score, "seen": float(now_s)}
            return True
        if cur is not None and cur["next_hop"] == next_hop:
            cur["seen"] = float(now_s); cur["link_rssi"] = rssi
            cur["link_snr"] = snr; cur["path_rssi"] = bottleneck_rssi
            cur["path_snr"] = bottleneck_snr; cur["score"] = score
        return False

    def next_hop(self, dest):
        r = self._items.get(int(dest)); return r["next_hop"] if r else None

    def get(self, dest): return self._items.get(int(dest))

    def expire(self, now_s, dead_neighbors=None):
        dead_neighbors = set(dead_neighbors or [])
        dead = []
        for d, r in list(self._items.items()):
            if float(now_s) - r["seen"] > self.expire_s or r["next_hop"] in dead_neighbors:
                dead.append(d); del self._items[d]
        return dead

    def items(self): return self._items.items()

    def __len__(self): return len(self._items)

# ═══════════════════════════════════════════════════════════════════════════════
# DTN QUEUE (from software/network/dtn_queue.py)
# ═══════════════════════════════════════════════════════════════════════════════

class DtnQueue:
    def __init__(self, max_items=16, ttl_s=30.0, retry_s=3.0):
        self.max_items = int(max_items); self.ttl_s = float(ttl_s)
        self.retry_s = float(retry_s); self._items = []

    def enqueue(self, packet, now_s):
        if getattr(packet, "ttl", 0) <= 0: return False
        key = (packet.src, packet.mid)
        for item in self._items:
            if item["key"] == key: return False
        while len(self._items) >= self.max_items: self._items.pop(0)
        self._items.append({"key": key, "packet": packet,
                            "born": float(now_s),
                            "next_try": float(now_s) + self.retry_s})
        return True

    def wake(self, dst, now_s):
        for item in self._items:
            if item["packet"].dst == int(dst): item["next_try"] = float(now_s)

    def pop_ready(self, route_table, now_s):
        ready = []; keep = []
        for item in self._items:
            p = item["packet"]
            if float(now_s) - item["born"] > self.ttl_s: continue
            if float(now_s) < item["next_try"]: keep.append(item); continue
            nh = route_table.next_hop(p.dst)
            if nh is None: item["next_try"] = float(now_s) + self.retry_s; keep.append(item); continue
            p.next_hop = nh; ready.append(p)
        self._items = keep
        return ready

    def __len__(self): return len(self._items)

# ═══════════════════════════════════════════════════════════════════════════════
# RADIO ADAPTER (from software/network/radio_adapter.py)
# ═══════════════════════════════════════════════════════════════════════════════

class RadioAdapter:
    def __init__(self, hardware): self.hardware = hardware

    def send(self, packet_bytes, use_lbt=False):
        radio = self.hardware.lora
        if radio is None: return False
        try:
            if use_lbt and hasattr(radio, "send_lbt"):
                ok = radio.send_lbt(packet_bytes, max_tries=3, base_backoff_ms=20)
            else:
                radio.send(packet_bytes); ok = True
            if hasattr(radio, "recv_start"): radio.recv_start()
            return bool(ok)
        except Exception as e:
            print("radio tx err: {0}".format(e))
            time.sleep(0.01)  # let driver recovery settle
            try:
                if hasattr(radio, "recv_start"): radio.recv_start()
            except Exception: pass
            return False

    def start_rx(self):
        radio = self.hardware.lora
        if radio is not None and hasattr(radio, "recv_start"):
            try: radio.recv_start()
            except Exception: pass

    def set_sf(self, sf):
        radio = self.hardware.lora
        if radio is not None and hasattr(radio, "set_sf"):
            radio.set_sf(int(sf))

    def cad(self, timeout_ms=250):
        """Hardware Channel Activity Detection. Returns True if LoRa preamble detected."""
        radio = self.hardware.lora
        if radio is not None and hasattr(radio, "cad"):
            try: return bool(radio.cad(timeout_ms=timeout_ms))
            except Exception: pass
        return False

    def poll(self, timeout_ms=300):
        radio = self.hardware.lora
        if radio is None: return None
        try:
            if hasattr(radio, "recv_poll"):
                result = radio.recv_poll()
                if result is None: return None
            else:
                result = radio.recv(timeout_en=True, timeout_ms=int(timeout_ms))
            if not (result and isinstance(result, tuple) and result[0]):
                if hasattr(radio, "recv_start"): radio.recv_start()
                return None
            if hasattr(radio, "recv_start"): radio.recv_start()
            return result[0]
        except Exception as e:
            print("radio rx err: {0}".format(e))
            try:
                if hasattr(radio, "recv_start"): radio.recv_start()
            except Exception: pass
            return None

    def rssi(self):
        try: return self.hardware.lora.getRSSI()
        except Exception: return -999

    def snr(self):
        try: return self.hardware.lora.getSNR()
        except Exception: return 0.0

# ═══════════════════════════════════════════════════════════════════════════════
# MESH NETWORK (from software/network/mesh.py)
# ═══════════════════════════════════════════════════════════════════════════════

class MeshNetwork:
    def __init__(self, node_id, radio, endpoint=None, event_sink=None, role='relay'):
        self.node_id = int(node_id); self.radio = radio
        self.endpoint = endpoint; self.event_sink = event_sink
        self.role = role
        self.codec = PacketCodec()
        self.neighbors = NeighborTable(expire_s=NEIGHBOR_EXPIRE_S)
        self.routes = RouteTable(expire_s=ROUTE_EXPIRE_S,
                                 switch_margin=ROUTE_SWITCH_MARGIN,
                                 rssi_margin_db=ROUTE_RSSI_MARGIN_DB,
                                 mode=ROUTE_MODE,
                                 reliable_hop_penalty_db=ROUTE_RELIABLE_HOP_PENALTY_DB,
                                 reliable_switch_margin_db=ROUTE_RELIABLE_SWITCH_MARGIN_DB)
        self.dtn = DtnQueue(max_items=DTN_QUEUE_MAX, ttl_s=DTN_TTL_S, retry_s=DTN_RETRY_S)
        self.data_cache  = DedupCache(CACHE_SIZE)
        self.route_cache = DedupCache(CACHE_SIZE)
        self.topo_tracker = TopologyTracker(cache_size=CACHE_SIZE, expire_s=TOPOLOGY_EXPIRE_S)
        self.msg_id = 0; self.route_mid = 0
        now = time.monotonic()
        h, r, t = MODE_INTERVALS[MODE_BOOT]
        self._last_hello  = now - h
        self._last_route  = now - r + ROUTE_TX_OFFSET_S
        self._last_topo   = now - t + TOPO_TX_OFFSET_S
        self._last_expire = now
        self._last_mgmt_tx = now - MGMT_TX_GAP_S
        self._topo_urgent = False
        self._last_topo_snapshot = {}   # for event-driven topology: skip if unchanged
        self._last_topo_sent = 0        # timestamp of last topology TX (for max-interval fallback)
        # Adaptive mode state
        self._mode = MODE_BOOT
        self._boot_start = now
        self._stable_periods = 0
        self._neighbor_snapshot = {}
        self._last_mode_check = now
        self._topo_seq = 0
        self._orient_seq = 0
        self._current_sf = LORA_SF
        self._last_neighbor_seen = now  # for isolation detection
        self._reconnect_scan_at = 0     # next scheduled re-scan (0 = none)

    def notify(self, msg):
        if self.event_sink is not None: self.event_sink.notify(msg)

    # ── SF scanning (boot discovery) ─────────────────────────────────────────

    def scan_for_network(self):
        """CAD-based fast SF scan. Returns True if existing network found."""
        if not SF_AUTO_ENABLED or _cfg['sf_mode'] != "auto":
            self.radio.set_sf(LORA_SF)
            self._current_sf = LORA_SF
            _cfg['network_sf'] = LORA_SF
            print("SCAN: SF7-only mode, skipping SF sweep")
            return False

        if not SF_SCAN_ENABLED:
            print("SCAN: disabled, staying at SF{0}".format(LORA_SF))
            return False

        # Reconnect fast path: try last-known SF first
        if self._current_sf != LORA_SF:
            print("SCAN: trying last SF{0}...".format(self._current_sf))
            self.radio.set_sf(self._current_sf)
            if self._cad_and_listen(self._current_sf):
                return True

        # CAD sweep SF7→SF12 (<100ms total)
        candidates = []
        print("SCAN: CAD sweep SF7→12...")
        for sf in range(7, 13):
            self.radio.set_sf(sf)
            self._current_sf = sf
            if self.radio.cad(timeout_ms=100):
                candidates.append(sf)
        print("SCAN: CAD hits at {0}".format(candidates))

        if not candidates:
            self.radio.set_sf(LORA_SF)
            self._current_sf = LORA_SF
            print("SCAN: no activity, starting at SF{0}".format(LORA_SF))
            return False

        # Listen on candidate SFs
        for sf in candidates:
            self.radio.set_sf(sf)
            self._current_sf = sf
            print("SCAN: listening SF{0}...".format(sf))
            if self._listen_for_hello(sf):
                return True

        self.radio.set_sf(LORA_SF)
        self._current_sf = LORA_SF
        print("SCAN: no HELLO heard, starting at SF{0}".format(LORA_SF))
        return False

    def _cad_and_listen(self, sf, listen_s=None):
        if listen_s is None: listen_s = SF_SCAN_TIMEOUT_S
        if not self.radio.cad(timeout_ms=100):
            return False
        return self._listen_for_hello(sf, listen_s)

    def _listen_for_hello(self, sf, listen_s=None):
        if listen_s is None: listen_s = SF_SCAN_TIMEOUT_S
        deadline = time.monotonic() + listen_s
        while time.monotonic() < deadline:
            raw = self.radio.poll(timeout_ms=200)
            if raw is None: continue
            try:
                pkt = self.codec.decode(raw)
                if isinstance(pkt, HelloPacket) and pkt.src != self.node_id:
                    net_sf = getattr(pkt, 'sf', 7)
                    if SF_AUTO_ENABLED and _cfg['sf_mode'] == "auto" and net_sf != sf:
                        self.radio.set_sf(net_sf)
                        self._current_sf = net_sf
                    print("SCAN: found N{0} SF{1}".format(pkt.src, net_sf))
                    return True
            except Exception: pass
        return False

    def _reconnect_scan(self):
        """Re-run CAD sweep to find the network after prolonged isolation.
        Called periodically when no neighbors are visible.
        In locked mode, only checks the locked SF (fast). In auto mode, sweeps all SFs.
        """
        if not SF_AUTO_ENABLED or _cfg['sf_mode'] != "auto":
            self.radio.set_sf(LORA_SF)
            self._current_sf = LORA_SF
            _cfg['network_sf'] = LORA_SF
            print("RECONNECT: SF7-only mode, no SF scan")
            return False

        print("RECONNECT: isolated, re-scanning SF7→12...")
        # CAD sweep
        candidates = []
        for sf in range(7, 13):
            self.radio.set_sf(sf)
            if self.radio.cad(timeout_ms=100):
                candidates.append(sf)
        print("RECONNECT: CAD hits at {0}".format(candidates))

        if not candidates:
            self.radio.set_sf(self._current_sf)
            return False

        # Listen on candidate SFs
        for sf in candidates:
            self.radio.set_sf(sf)
            if self._listen_for_hello(sf, SF_SCAN_TIMEOUT_S):
                return True

        # Nothing found — stay at current SF and keep trying
        self.radio.set_sf(self._current_sf)
        print("RECONNECT: no network found, staying SF{0}".format(self._current_sf))
        return False

    # ── transmit ────────────────────────────────────────────────────────────

    def send_hello(self, role=None):
        r = role or "?"
        sf = getattr(self, '_current_sf', LORA_SF)
        ok = self.radio.send(self.codec.encode_hello(self.node_id, r, sf))
        if ok:
            log_event("TX_H", "N{0}|{1}|SF{2}".format(self.node_id, r, sf))
        else:
            log_event("TX_FAIL", "H N{0}|{1}|SF{2}".format(self.node_id, r, sf))
        return ok

    def send_route_ad(self):
        self.route_mid = (self.route_mid + 1) & 0xFF
        ok = self.radio.send(self.codec.encode_route_ad(
            self.node_id, self.node_id, self.route_mid, 0))
        if ok:
            print("TX R mid={0}".format(self.route_mid))
        else:
            print("TX_FAIL R mid={0}".format(self.route_mid))
        return ok

    def set_route_mode(self, mode, broadcast=False):
        mode = str(mode or "").strip().lower()
        self.routes.set_mode(mode)
        _cfg['route_mode'] = self.routes.mode
        self.notify("MESH_ROUTE_MODE:{0}".format(self.routes.mode))
        print("ROUTE_MODE:{0}".format(self.routes.mode))
        if broadcast:
            self.send_data(0, "ROUTE_MODE:{0}".format(self.routes.mode), allow_dtn=False)

    def _next_hop_for(self, dst):
        dst = int(dst)
        nh = self.routes.next_hop(dst)
        if nh is not None:
            return nh
        if self.neighbors.has(dst):
            return dst
        nh = self.topo_tracker.next_hop(self.node_id, dst, self.neighbors.snapshot(),
                                        mode=self.routes.mode)
        if nh is not None:
            print("TOPO_ROUTE dst=N{0} via=N{1}".format(dst, nh))
        return nh

    def send_data(self, dst, payload, allow_dtn=True, use_lbt=True):
        self.msg_id = (self.msg_id + 1) & 0xFF
        self.data_cache.mark((self.node_id, self.msg_id))
        next_hop = 0 if int(dst) == 0 else self._next_hop_for(dst)
        pkt = DataPacket(self.node_id, int(dst), next_hop or 0,
                         self.msg_id, TTL_DEFAULT, payload)
        if int(dst) != 0 and next_hop is None:
            if allow_dtn and not _is_control_payload(payload):
                self.dtn.enqueue(pkt, time.monotonic())
                self.notify("MESH_ERR:NO_ROUTE:{0}".format(dst))
                print("DTN queue dst=N{0} mid={1}".format(dst, self.msg_id))
            else:
                self.notify("MESH_ERR:NO_ROUTE:{0}".format(dst))
            return False
        ok = self.radio.send(
            self.codec.encode_data(pkt.src, pkt.dst, pkt.next_hop,
                                   pkt.mid, pkt.ttl, pkt.payload),
            use_lbt=use_lbt)
        if ok:
            self.notify("MESH_TX:{0}|{1}|{2}|{3}|{4}|{5}".format(
                pkt.src, pkt.dst, pkt.next_hop, pkt.mid, pkt.ttl, pkt.payload))
            if pkt.next_hop and pkt.next_hop != pkt.dst:
                hop = "→N{0}→".format(pkt.next_hop)
            else:
                hop = "→"
            log_event("TX_D", "N{0}{1}N{2} mid={3} '{4}'".format(
                pkt.src, hop, pkt.dst, pkt.mid, pkt.payload))
        return ok

    # ── topology / orientation ──────────────────────────────────────────────

    def send_topology_report(self):
        """Broadcast T payload so all nodes (including controller) see the topology."""
        if not _cfg['report_topo']: return False
        self._topo_seq = (self._topo_seq + 1) & 0xFF
        neighbors = self.neighbors.snapshot()
        payload = self.codec.encode_topology(self.node_id, self._topo_seq, neighbors)
        # Topology is already staggered by the scheduler. Do not run it through
        # CAD/LBT because false busy readings can suppress every report silently.
        ok = self.send_data(0, payload, allow_dtn=False, use_lbt=False)
        if ok:
            print("TX T seq={0} nbrs={1}".format(self._topo_seq, len(neighbors)))
        else:
            print("TX_FAIL T seq={0} nbrs={1}".format(self._topo_seq, len(neighbors)))
        return ok

    def send_orientation(self, dst):
        """Send O payload to a newly discovered node with our route table."""
        self._orient_seq = (self._orient_seq + 1) & 0xFF
        routes = {}
        for dest, rt in self.routes.items():
            routes[dest] = rt["hops"]
        # Include our direct neighbors too (1 hop)
        for nid in self.neighbors.snapshot():
            if nid not in routes: routes[nid] = 1
        payload = self.codec.encode_orientation(self.node_id, int(dst),
                                                 self._orient_seq, routes)
        self.send_data(int(dst), payload, allow_dtn=False)

    # ── adaptive mode ───────────────────────────────────────────────────────

    def _mode_name(self):
        return ["BOOT","ACTIVE","NORMAL","QUIET"][self._mode]

    def _set_mode(self, mode):
        if mode == self._mode: return
        old = self._mode_name()
        self._mode = mode
        self._stable_periods = 0
        h, r, t = MODE_INTERVALS[mode]
        now = time.monotonic()
        self._last_hello = now - h
        self._last_route = now - r + ROUTE_TX_OFFSET_S
        self._last_topo  = now - t + TOPO_TX_OFFSET_S
        log_event("MODE", "{0}→{1}".format(old, self._mode_name()))

    def _topo_interval(self):
        _, _, t_int = MODE_INTERVALS[self._mode]
        return _cfg['topo_interval'] if _cfg['topo_interval'] > 0 else t_int

    def _schedule_topology_report(self, now=None, delay_s=None):
        if now is None: now = time.monotonic()
        # Minimum gap between topology reports — prevents flooding on
        # RSSI fluctuations while still being responsive to real changes.
        # Allow if never sent before (_last_topo_sent == 0).
        if self._last_topo_sent > 0 and now - self._last_topo_sent < TOPO_MIN_REPORT_GAP_S:
            return
        if delay_s is None:
            delay_s = TOPO_TX_OFFSET_S + random.uniform(0.0, 0.75)
        topo_int = self._topo_interval()
        current_due = self._last_topo + topo_int
        requested_due = float(now) + float(delay_s)
        if requested_due < current_due:
            self._last_topo = requested_due - topo_int
        self._topo_urgent = True

    def set_sf(self, sf_or_auto):
        """Public: apply SF change locally, then broadcast to network.
        FROZEN: only SF7 is accepted while base connectivity is being validated.
        """
        print("SF: frozen at SF7 — ignoring {0}".format(sf_or_auto))

    def _apply_sf_change(self, force=False, broadcast=False):
        """Switch radio to current network_sf and announce the change."""
        new_sf = _cfg['network_sf']
        if new_sf == self._current_sf: return
        # Cooldown: no SF change within 30s of the last one (skipped for explicit commands)
        last = getattr(self, '_last_sf_change', 0)
        if not force and time.monotonic() - last < 30.0:
            return
        self._last_sf_change = time.monotonic()
        old_sf = self._current_sf
        self.radio.set_sf(new_sf)
        self._current_sf = new_sf
        log_event("SF_CHG", "{0}→{1}".format(old_sf, new_sf))
        self.notify("MESH_SF:{0}".format(new_sf))
        # Broadcast so other nodes follow immediately — avoids SF desync
        if broadcast:
            self.send_data(0, "SF:{0}".format(new_sf), allow_dtn=False)
            print("TX SF broadcast →SF{0}".format(new_sf))

    def _check_mode_transition(self, now):
        if self._mode == MODE_BOOT:
            if now - self._boot_start >= BOOT_DURATION:
                self._set_mode(MODE_NORMAL)
            return

        # Isolated node — stay in ACTIVE mode for fast reconnection.
        # Check _last_neighbor_seen age, not dict emptiness (neighbors linger for 120s until expire()).
        # Locked-SF mode uses shorter timeout (30s) since there's no SF mismatch risk.
        isolation_s = 30.0 if _cfg['sf_mode'] != "auto" else NEIGHBOR_EXPIRE_S
        if now - self._last_neighbor_seen > isolation_s:
            if self._mode != MODE_ACTIVE:
                self._set_mode(MODE_ACTIVE)
            return

        cur = self.neighbors.snapshot()
        if self.neighbors.changed_since(self._neighbor_snapshot, RSSI_CHANGE_THRESH):
            self._stable_periods = 0
            if self._mode != MODE_ACTIVE:
                self._set_mode(MODE_ACTIVE)
        else:
            self._stable_periods += 1

        self._neighbor_snapshot = cur

        if self._mode == MODE_ACTIVE and self._stable_periods >= STABLE_CHECKS:
            self._set_mode(MODE_NORMAL)
        elif self._mode == MODE_NORMAL and self._stable_periods >= STABLE_CHECKS:
            self._set_mode(MODE_QUIET)

    # ── periodic tick ───────────────────────────────────────────────────────

    def tick(self):
        now = time.monotonic()
        h_int, r_int, t_int = MODE_INTERVALS[self._mode]
        topo_int = _cfg['topo_interval'] if _cfg['topo_interval'] > 0 else t_int

        # Mode transition check — only once per check interval (10s), not every tick
        if now - self._last_mode_check >= 10.0:
            self._last_mode_check = now
            self._check_mode_transition(now)

        # SF re-scan is disabled while the network is frozen to SF7.
        # Keep the auto-SF code path behind sf_mode == "auto" for future work.
        if SF_AUTO_ENABLED and _cfg['sf_mode'] == "auto":
            if (now - self._last_neighbor_seen > NEIGHBOR_EXPIRE_S
                    and now >= self._reconnect_scan_at):
                self._reconnect_scan()
                self._reconnect_scan_at = now + 60.0

        if now - self._last_mgmt_tx >= MGMT_TX_GAP_S:
            # Topology is event-driven: send on neighbour change, or max interval fallback.
            # This eliminates redundant T: packets that carry the same RSSI/SNR every cycle.
            topo_changed = self.neighbors.changed_since(self._last_topo_snapshot, TOPO_CHANGE_RSSI_DB)
            topo_overdue = (now - self._last_topo_sent) >= topo_int
            if self._topo_urgent or (topo_changed and topo_overdue):
                self._last_topo = now
                self._last_mgmt_tx = now
                self._topo_urgent = False
                sent = self.send_topology_report()
                # Always update timers — even on TX failure, to avoid tight retry loops
                self._last_topo_snapshot = self.neighbors.snapshot()
                self._last_topo_sent = now
                if sent:
                    pass  # TX succeeded (logged inside send_topology_report)
            elif now - self._last_hello >= h_int:
                self._last_hello = now
                self._last_mgmt_tx = now
                self.send_hello(role=self.role)
            elif now - self._last_route >= r_int:
                self._last_route = now
                self._last_mgmt_tx = now
                self.send_route_ad()
            elif topo_overdue:
                # Max interval fallback — send even if unchanged, then reset timer
                self._last_topo = now
                self._last_mgmt_tx = now
                self.send_topology_report()
                self._last_topo_snapshot = self.neighbors.snapshot()
                self._last_topo_sent = now
        # Adaptive SF — periodic downgrade check
        if SF_AUTO_ENABLED and _cfg['sf_mode'] == "auto" and sf_check_down(self.neighbors._items, now):
            self._apply_sf_change(broadcast=True)
        if now - self._last_expire >= EXPIRE_INTERVAL_S:
            self._last_expire = now
            dead_nb = self.neighbors.expire(now)
            dead_rt = self.routes.expire(now, dead_neighbors=dead_nb)
            dead_topo = self.topo_tracker.expire(now)
            if dead_nb: print("expired nb: {0}".format(dead_nb))
            if dead_rt: print("expired rt: {0}".format(dead_rt))
            if dead_nb:
                self._set_mode(MODE_ACTIVE)
                self._schedule_topology_report(now=now, delay_s=0.1)
            for nid in dead_topo:
                self.notify("MESH_NODE_REMOVE:{0}".format(nid))
            if dead_topo: print("expired topo: {0}".format(dead_topo))
        for pkt in self.dtn.pop_ready(self.routes, now):
            enc = self.codec.encode_data(pkt.src, pkt.dst, pkt.next_hop,
                                         pkt.mid, pkt.ttl, pkt.payload)
            print("DTN→ N{0}→N{1} mid={2}".format(pkt.src, pkt.dst, pkt.mid))
            if not self.radio.send(enc, use_lbt=True):
                self.dtn.enqueue(pkt, now)

    # ── radio poll ──────────────────────────────────────────────────────────

    def poll_radio(self):
        raw = self.radio.poll()
        if raw is None: return
        try: pkt = self.codec.decode(raw)
        except Exception as e: print("decode err: {0}".format(e)); return
        if isinstance(pkt, HelloPacket):    self._on_hello(pkt)
        elif isinstance(pkt, RouteAdPacket): self._on_route(pkt)
        elif isinstance(pkt, DataPacket):    self._on_data(pkt)

    def _on_hello(self, pkt):
        if pkt.src == self.node_id: return
        rssi = self.radio.rssi(); snr = self.radio.snr()
        self._last_neighbor_seen = time.monotonic()
        now = time.monotonic()
        prev = self.neighbors.get(pkt.src)
        is_new = prev is None
        topology_changed = (
            is_new or
            (prev.get("role", "?") != pkt.role if prev else False) or
            (abs(int(rssi) - int(prev.get("rssi", rssi))) > RSSI_CHANGE_THRESH if prev else False)
        )
        wakes_controller = (pkt.role == "C" or pkt.src == CONTROLLER_ID)
        should_orient = is_new or (wakes_controller and self._mode == MODE_QUIET)
        self.neighbors.update(pkt.src, rssi=rssi, snr=snr, role=pkt.role, now_s=now)
        # Direct neighbor = 1 hop away; install route immediately so WELCOME can reach them
        self.routes.update(pkt.src, pkt.src, 0, link_rssi=rssi, link_snr=snr, now_s=now)
        self.notify("MESH_NB:{0}|{1}|{2:.1f}|{3}".format(pkt.src, rssi, snr, pkt.role))
        log_event("RX_H", "N{0}|{1}|rssi={2} snr={3:.0f}".format(pkt.src, pkt.role, rssi, snr))
        if topology_changed:
            self._schedule_topology_report(now, delay_s=TOPO_TX_OFFSET_S + random.uniform(0.0, 1.0))
        if should_orient:
            if not is_new:
                self._set_mode(MODE_ACTIVE)
            self.send_data(pkt.src, "WELCOME:{0}".format(self.role), allow_dtn=False)
            print("TX WELCOME to N{0}".format(pkt.src))
            # Orient the new node about our known network
            self.send_orientation(pkt.src)
            # Report topology shortly after WELCOME/O instead of in the same burst.
            self._schedule_topology_report(now, delay_s=TOPO_TX_OFFSET_S + random.uniform(0.0, 1.0))
        # Adaptive SF check — escalate immediately if needed
        if SF_AUTO_ENABLED and _cfg['sf_mode'] == "auto" and sf_check_up(self.neighbors._items):
            self._apply_sf_change(broadcast=True)

    def _on_route(self, pkt):
        if pkt.orig == self.node_id:
            return
        rssi = self.radio.rssi(); snr = self.radio.snr()
        self._last_neighbor_seen = time.monotonic()
        self.neighbors.update(pkt.fwd, rssi=rssi, snr=snr, now_s=time.monotonic())
        # Always try to install/update the route — a better path may arrive
        # after a worse one was already cached (different forwarders, same orig+mid)
        improved = self.routes.update(pkt.orig, pkt.fwd, pkt.hops,
                                      link_rssi=rssi, link_snr=snr,
                                      path_rssi=pkt.path_rssi, path_snr=pkt.path_snr,
                                      now_s=time.monotonic())
        route = self.routes.get(pkt.orig) or {}
        already_seen = self.route_cache.seen((pkt.orig, pkt.mid))
        if not already_seen:
            self.route_cache.mark((pkt.orig, pkt.mid))
        print("RX R N{0}←N{1} hops={2} mid={3} →nh=N{4} total={5} {6}".format(
            pkt.orig, pkt.fwd, pkt.hops, pkt.mid,
            route.get("next_hop", "?"), route.get("hops", "?"),
            "[NEW]" if improved else "[known]"))
        if improved:
            self.dtn.wake(pkt.orig, time.monotonic())
            self.notify("MESH_ROUTE:{0}|{1}|{2}".format(
                pkt.orig, route["next_hop"], route["hops"]))
        # Forward only if not already seen — prevent broadcast storms
        if not already_seen and pkt.hops + 1 < ROUTE_TTL:
            route = self.routes.get(pkt.orig) or {}
            time.sleep(random.uniform(ROUTE_JITTER_MIN_S, ROUTE_JITTER_MAX_S))
            self.radio.send(
                self.codec.encode_route_ad(pkt.orig, self.node_id, pkt.mid, pkt.hops + 1,
                                           route.get("path_rssi"), route.get("path_snr")),
                use_lbt=True)

    def _on_data(self, pkt):
        if pkt.src == self.node_id: return
        is_broadcast = pkt.dst == 0 or pkt.next_hop == 0
        is_for_me = pkt.dst == self.node_id or pkt.next_hop == self.node_id
        # Passive route learning: overheard packets tell us who can reach whom
        if not is_for_me and not is_broadcast and pkt.next_hop and pkt.next_hop != 0:
            hops_est = TTL_DEFAULT - pkt.ttl + 1
            self.routes.update(pkt.src, pkt.next_hop, hops_est - 1,
                               link_rssi=None, link_snr=None, now_s=time.monotonic())
        if not is_broadcast and not is_for_me: return
        if self.data_cache.seen((pkt.src, pkt.mid)): return
        self.data_cache.mark((pkt.src, pkt.mid))
        rssi = self.radio.rssi(); snr = self.radio.snr()
        if pkt.next_hop and pkt.next_hop != pkt.dst and pkt.next_hop != 0:
            nh_str = "→N{0}→".format(pkt.next_hop)
        else:
            nh_str = "→"
        print("RX D N{0}{1}N{2} mid={3} ttl={4} rssi={5} snr={6:.1f} '{7}'".format(
            pkt.src, nh_str, pkt.dst, pkt.mid, pkt.ttl, rssi, snr, pkt.payload))
        if pkt.dst == 0 or pkt.dst == self.node_id:
            payload_str = str(pkt.payload)
            if payload_str.startswith("WELCOME:"):
                role = payload_str[8:]
                self.neighbors.update(pkt.src, role=role, now_s=time.monotonic())
                self.notify("MESH_NB:{0}|{1}|{2:.1f}|{3}".format(pkt.src, rssi, snr, role))
                print("RX WELCOME from N{0} role={1}".format(pkt.src, role))
            elif payload_str.startswith("TOPO:"):
                cmd = payload_str[5:]
                if cmd == "ON":
                    _cfg['report_topo'] = True; print("TOPO: reporting ON")
                elif cmd == "OFF":
                    _cfg['report_topo'] = False; print("TOPO: reporting OFF")
                elif cmd.startswith("INTERVAL:"):
                    try:
                        _cfg['topo_interval'] = int(cmd[9:])
                        print("TOPO: interval={0}s".format(_cfg['topo_interval']))
                    except ValueError:
                        print("TOPO: bad interval")
            elif payload_str.startswith("SF:"):
                # FROZEN: SF7-only, ignore all SF commands
                print("SF: frozen — dropping over-the-air SF command")
                return
            elif payload_str.startswith("ROUTE_MODE:"):
                self.set_route_mode(payload_str[11:], broadcast=False)
            elif payload_str.startswith("MODE:"):
                val = payload_str[5:]
                if val == "QUIET":   self._set_mode(MODE_QUIET)
                elif val == "NORMAL": self._set_mode(MODE_NORMAL)
                elif val == "ACTIVE": self._set_mode(MODE_ACTIVE)
                else: print("MODE: bad value ({0})".format(val))
            elif payload_str.startswith("T:"):
                try:
                    tp = self.codec._decode_topology(payload_str)
                    added, _ = self.topo_tracker.feed(tp, time.monotonic())
                    for nid in added:
                        self.notify("MESH_NODE_ADD:{0}".format(nid))
                    # Push full edge list (BLE path + serial path)
                    edges = self.topo_tracker.edges()
                    parts = ["{0},{1},{2},{3:.1f}".format(a, b, r, s) for a, b, r, s in edges]
                    topo_line = "MESH_TOPOLOGY:" + (";".join(parts) if parts else "none")
                    self.notify(topo_line)
                    print(topo_line)
                    # Also print each edge so serial-connected dashboards can parse
                    for a, b, r, s in edges:
                        print("TOPO_EDGE:N{0}-N{1}|RSSI:{2}|SNR:{3:.1f}".format(a, b, r, s))
                    print("RX T from N{0} seq={1} nbrs={2}".format(
                        tp.src, tp.seq, len(tp.neighbors)))
                except Exception as e:
                    print("topo decode err: {0}".format(e))
            elif payload_str.startswith("O:"):
                try:
                    op = self.codec._decode_orientation(payload_str)
                    if op.dst == self.node_id:
                        for dest, hops in op.routes.items():
                            self.routes.update(dest, op.src, hops,
                                               link_rssi=rssi, link_snr=snr,
                                               now_s=time.monotonic())
                        print("RX O from N{0} routes={1}".format(op.src, len(op.routes)))
                except Exception as e:
                    print("orient decode err: {0}".format(e))
            # Drop broadcast control payloads on non-endpoint nodes (avoid
            # actuation commands flooding the network). Endpoint nodes still
            # process them so SERVO/PING/CAPS? work over broadcast.
            if pkt.dst == 0 and _is_control_payload(pkt.payload):
                if self.endpoint is None:
                    self.notify("MESH_DROP:BROADCAST_CONTROL:{0}:{1}".format(pkt.src, pkt.mid))
                    return
                # Endpoint present — deliver control payload to it below
            self.notify("MESH_RX:{0}|{1}|{2}|{3}|{4}|{5:.1f}|{6}".format(
                pkt.src, pkt.dst, pkt.mid, pkt.ttl, rssi, snr, pkt.payload))
            if self.endpoint is not None: self.endpoint.on_data(pkt, self)
        if pkt.dst == self.node_id or pkt.ttl <= 1: return
        if pkt.next_hop == 0:
            # Topology reports always forward. SF commands are frozen and dropped above.
            payload_str = str(pkt.payload)
            if not (payload_str.startswith("T:") or payload_str.startswith("ROUTE_MODE:")):
                if random.random() > _relay_probability(rssi): return
            time.sleep(random.uniform(RELAY_JITTER_MIN_S, RELAY_JITTER_MAX_S))
            self.radio.send(self.codec.encode_data(
                pkt.src, pkt.dst, 0, pkt.mid, pkt.ttl - 1, pkt.payload), use_lbt=True)
            return
        if pkt.next_hop != self.node_id: return
        next_hop = self._next_hop_for(pkt.dst)
        if next_hop is None:
            if not _is_control_payload(pkt.payload):
                pkt.ttl -= 1; self.dtn.enqueue(pkt, time.monotonic())
                print("DTN relay queue dst=N{0} mid={1}".format(pkt.dst, pkt.mid))
            else:
                print("DROP relay no route dst=N{0} mid={1} control".format(pkt.dst, pkt.mid))
            return
        time.sleep(random.uniform(RELAY_JITTER_MIN_S, RELAY_JITTER_MAX_S))
        ok = self.radio.send(self.codec.encode_data(
            pkt.src, pkt.dst, next_hop, pkt.mid, pkt.ttl - 1, pkt.payload), use_lbt=True)
        if ok:
            print("FWD D N{0}→N{1}→N{2} mid={3} ttl={4}".format(
                pkt.src, next_hop, pkt.dst, pkt.mid, pkt.ttl - 1))
        else:
            print("FWD_FAIL D N{0}→N{1}→N{2} mid={3}".format(
                pkt.src, next_hop, pkt.dst, pkt.mid))

def _relay_probability(rssi):
    if rssi > -60: return 0.40
    if rssi > -75: return 0.65
    if rssi > -90: return 0.85
    return 0.97

def _is_control_payload(payload):
    return str(payload).startswith(CONTROL_PREFIXES)

# ── Event log writer (writes mesh_log.csv on CIRCUITPY if LOG_TO_FILE=True) ──

def log_event(event_type, details):
    """Write a structured event line. If LOG_TO_FILE, also append to mesh_log.csv."""
    ts = time.monotonic()
    line = "[{0:7.1f}] {1} {2}".format(ts, event_type, details)
    print(line)
    if not LOG_TO_FILE: return
    try:
        fn = "mesh_log.csv"
        _cfg['log_lines'] = _cfg.get('log_lines', 0) + 1
        if _cfg['log_lines'] >= LOG_FILE_MAX_LINES:
            _cfg['log_lines'] = 0
            try:
                import os
                for i in range(5, 0, -1):
                    old = "mesh_log.{0}.csv".format(i) if i > 1 else "mesh_log.old.csv"
                    newer = "mesh_log.{0}.csv".format(i + 1) if i < 5 else "mesh_log.csv"
                    try: os.rename(old, newer)
                    except Exception: pass
            except Exception: pass
        with open(fn, "a") as f:
            f.write("{0:.1f},{1},{2}\n".format(ts, event_type, details.replace(",", ";")))
    except Exception:
        pass  # silently ignore write errors (disk full, etc.)

# ── Adaptive SF checks ──────────────────────────────────────────────────────

def sf_check_up(neighbor_table):
    """Escalate network_sf if any direct link is persistently degraded.
    Requires SF_UP_CONSECUTIVE consecutive readings below threshold before acting."""
    if _cfg['network_sf'] >= 12: return False
    sf = _cfg['network_sf']
    snr_hold = SF_HOLD.get(sf, -99)
    rssi_hold = SF_RSSI_HOLD.get(sf, -130)
    degraded = False
    for nb in neighbor_table.values():
        if nb.get("snr", 0) < snr_hold or nb.get("rssi", 0) < rssi_hold:
            degraded = True
            break
    if degraded:
        _cfg['sf_bad_count'] = _cfg.get('sf_bad_count', 0) + 1
        if _cfg['sf_bad_count'] >= SF_UP_CONSECUTIVE:
            _cfg['network_sf'] += 1
            _cfg['sf_good_since'] = None
            _cfg['sf_bad_count'] = 0
            return True
    else:
        _cfg['sf_bad_count'] = 0
    return False

def sf_check_down(neighbor_table, now_s):
    """De-escalate network_sf after sustained good links. Returns True if changed."""
    if _cfg['network_sf'] <= 7 or not neighbor_table: return False
    down = SF_DOWN.get(_cfg['network_sf'], 99)
    all_good = all(nb.get("snr", -99) > down for nb in neighbor_table.values())
    if not all_good:
        _cfg['sf_good_since'] = None
        return False
    if _cfg['sf_good_since'] is None:
        _cfg['sf_good_since'] = now_s
        return False
    if now_s - _cfg['sf_good_since'] >= SF_DOWN_HOLD_S:
        _cfg['network_sf'] -= 1
        _cfg['sf_good_since'] = None
        return True
    return False

# ═══════════════════════════════════════════════════════════════════════════════
# TOPOLOGY TRACKER — aggregates T reports into a full network graph
# ═══════════════════════════════════════════════════════════════════════════════

class TopologyTracker:
    def __init__(self, cache_size=60, expire_s=180.0):
        self.cache_size = int(cache_size)
        self.expire_s = float(expire_s)
        self._graph = {}        # {node_id: {neighbor_id: rssi}}
        self._seen = {}         # {(src, seq): True} dedup
        self._known = set()     # set of all known node IDs
        self._last_seen = {}    # {node_id: timestamp} for expiry

    def feed(self, pkt, now_s):
        """Process a TopologyPacket, return (added_nodes, removed_nodes)."""
        if (pkt.src, pkt.seq) in self._seen:
            return [], []
        self._seen[(pkt.src, pkt.seq)] = True
        if len(self._seen) > self.cache_size:
            self._seen.pop(next(iter(self._seen)))

        added = []
        old_neighbors = set(self._graph.get(pkt.src, {}).keys())
        new_neighbors = set(pkt.neighbors.keys())

        # Store (rssi, snr) per neighbor; normalize legacy int-only values
        norm = {}
        for nid, val in pkt.neighbors.items():
            if isinstance(val, tuple):
                norm[nid] = val
            else:
                norm[nid] = (int(val), 0.0)
        self._graph[pkt.src] = norm
        self._last_seen[pkt.src] = float(now_s)

        for nid in new_neighbors:
            self._last_seen[nid] = float(now_s)
            if nid not in self._known:
                self._known.add(nid); added.append(nid)

        return added, []  # removed handled by expire()

    def expire(self, now_s):
        """Remove stale nodes, return list of removed node IDs."""
        removed = []
        for nid in list(self._last_seen.keys()):
            if float(now_s) - self._last_seen[nid] > self.expire_s:
                del self._last_seen[nid]
                self._graph.pop(nid, None)
                if nid in self._known:
                    self._known.discard(nid); removed.append(nid)
                # Clean dangling references
                for src in list(self._graph.keys()):
                    if nid in self._graph.get(src, {}):
                        del self._graph[src][nid]
        return removed

    def edges(self):
        """Return deduplicated edge list: [(a, b, rssi, snr), ...]."""
        result = []
        seen = set()
        for src, neighbors in self._graph.items():
            for nbr, val in neighbors.items():
                key = (min(src, nbr), max(src, nbr))
                if key not in seen:
                    seen.add(key)
                    if isinstance(val, tuple):
                        rssi, snr = val
                    else:
                        rssi, snr = int(val), 0.0
                    result.append((key[0], key[1], rssi, snr))
        return result

    def next_hop(self, src, dst, direct_neighbors, mode="fastest"):
        """Return first hop from src to dst using fresh topology edges."""
        src = int(src); dst = int(dst)
        if src == dst: return None
        graph = {}
        metrics = {}
        def add_edge(a, b, rssi=-999, snr=0.0):
            a = int(a); b = int(b)
            graph.setdefault(a, set()).add(b)
            graph.setdefault(b, set()).add(a)
            key = (min(a, b), max(a, b))
            metrics[key] = (int(rssi), float(snr))
        for a, b, r, s in self.edges():
            add_edge(a, b, r, s)
        if hasattr(direct_neighbors, "items"):
            direct_iter = direct_neighbors.items()
            for nid, val in direct_iter:
                if isinstance(val, tuple):
                    r, s = val
                else:
                    r, s = val, 0.0
                add_edge(src, nid, r, s)
        else:
            for nid in direct_neighbors:
                add_edge(src, nid)
        if src not in graph or dst not in graph:
            return None
        if str(mode).lower() == "reliable":
            queue = [(0.0, src, None)]
            best = {src: 0.0}
            while queue:
                queue.sort(key=lambda item: item[0])
                cost, node, first_hop = queue.pop(0)
                if node == dst:
                    return first_hop
                if cost > best.get(node, 999999):
                    continue
                for nbr in sorted(graph.get(node, [])):
                    key = (min(node, nbr), max(node, nbr))
                    rssi, snr = metrics.get(key, (-999, 0.0))
                    link_cost = max(1.0, -float(rssi) - (float(snr) * 2.0))
                    new_cost = cost + link_cost + 3.0
                    if new_cost < best.get(nbr, 999999):
                        best[nbr] = new_cost
                        queue.append((new_cost, nbr, nbr if node == src else first_hop))
            return None
        queue = [(src, None)]
        seen = set([src])
        while queue:
            node, first_hop = queue.pop(0)
            for nbr in sorted(graph.get(node, [])):
                if nbr in seen: continue
                hop = nbr if node == src else first_hop
                if nbr == dst:
                    return hop
                seen.add(nbr)
                queue.append((nbr, hop))
        return None

    def known_nodes(self):
        return sorted(self._known)

# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS (from software/endpoints/)
# ═══════════════════════════════════════════════════════════════════════════════

class BaseEndpoint:
    def tick(self, mesh): pass
    def on_data(self, packet, mesh): pass
    def on_local_command(self, command, mesh): return False

class ControllerEndpoint(BaseEndpoint):
    def on_data(self, packet, mesh):
        print("DELIVER C N{0}→N{1} '{2}'".format(packet.src, packet.dst, packet.payload))
        if str(packet.payload).startswith("PARROT:"):
            mesh.send_data(packet.src, "PONG:{0}:{1}".format(
                mesh.node_id, str(packet.payload)[7:]), allow_dtn=False)

class GadgetEndpoint(BaseEndpoint):
    def __init__(self, capabilities=None):
        self.capabilities = capabilities or {}
        self.debug_enabled = False
        self.debug_target = int(ENDPOINT_DEBUG_TARGET_NODE)
        self._last_debug_s = time.monotonic()

    def on_data(self, packet, mesh):
        if packet.dst != mesh.node_id: return
        payload = str(packet.payload)
        print("DELIVER E N{0}→N{1} '{2}'".format(packet.src, packet.dst, payload))
        if payload == "PING":
            mesh.send_data(packet.src, "ACK:PING:{0}".format(mesh.node_id), allow_dtn=False)
        elif payload == "CAPS?":
            caps = ",".join(sorted(self.capabilities.keys())) or "none"
            mesh.send_data(packet.src, "CAPS:{0}:{1}".format(mesh.node_id, caps), allow_dtn=False)
        elif payload.startswith("SERVO:"):
            self._handle_servo(packet, mesh, payload)
        elif self._is_control_command(payload):
            self._handle_control_command(payload, packet.src, mesh)
        elif payload.startswith("ENDPOINT:DEBUG"):
            self._handle_debug_command(payload, packet.src, mesh)
        elif payload.startswith("CMD:") or payload.startswith("ENDPOINT:"):
            mesh.send_data(packet.src, "ERROR:ENDPOINT:UNSUPPORTED", allow_dtn=False)

    def tick(self, mesh):
        if not self.debug_enabled: return
        now = time.monotonic()
        if now - self._last_debug_s < ENDPOINT_DEBUG_INTERVAL_S: return
        self._last_debug_s = now
        self._debug_seq = getattr(self, '_debug_seq', 0) + 1
        mesh.send_data(self.debug_target, "P{0}".format(self._debug_seq), allow_dtn=False)

    def on_local_command(self, command, mesh):
        text = str(command).strip()
        if not text: return False
        if text.startswith("SERVO:"):
            self._handle_servo_local(mesh, text)
            return True
        if text.startswith("DEBUG"):
            if ":" in text: text = "ENDPOINT:" + text
            else: text = text.replace("DEBUG ", "ENDPOINT:DEBUG:", 1)
            if text == "DEBUG": text = "ENDPOINT:DEBUG:ON"
            self._handle_debug_command(text, mesh.node_id, mesh)
            return True
        return False

    def _handle_servo_local(self, mesh, payload):
        servo = self.capabilities.get("servo")
        if servo is None: print("no servo capability"); return
        parts = payload[6:].split(":")
        try:
            angle = servo.move_angle(float(parts[-1]),
                                     min_angle=ENDPOINT_SERVO_MIN_ANGLE,
                                     max_angle=ENDPOINT_SERVO_MAX_ANGLE)
            print("servo angle={0:.1f}".format(angle))
        except Exception as e:
            print("servo err: {0}".format(e))

    def _handle_servo(self, packet, mesh, payload):
        servo = self.capabilities.get("servo")
        if servo is None:
            mesh.send_data(packet.src, "ERROR:SERVO:NO_CAPABILITY", allow_dtn=False)
            return
        parts = payload[6:].split(":")
        try:
            angle = servo.move_angle(float(parts[-1]),
                                     min_angle=ENDPOINT_SERVO_MIN_ANGLE,
                                     max_angle=ENDPOINT_SERVO_MAX_ANGLE)
        except Exception:
            mesh.send_data(packet.src, "ERROR:SERVO:BAD_ANGLE", allow_dtn=False)
            return
        print("endpoint servo angle={0:.1f}".format(angle))
        mesh.send_data(packet.src, "ACK:SERVO:{0:.1f}".format(angle), allow_dtn=False)

    def _is_control_command(self, payload):
        text = str(payload or "").strip().upper()
        if not text:
            return False
        if text in ("F", "B", "L", "R", "S", "+", "-", "FORWARD", "BACKWARD",
                    "LEFT", "RIGHT", "STOP", "FWRD", "BACK", "RGHT"):
            return True
        return text.startswith(("H:", "V:", "HEADING:", "SPEED:", "F:", "B:", "FWD:", "BACK:"))

    def _validate_control_command(self, payload):
        text = str(payload or "").strip()
        upper = text.upper()
        if upper in ("F", "B", "L", "R", "S", "+", "-", "FORWARD", "BACKWARD",
                     "LEFT", "RIGHT", "STOP", "FWRD", "BACK", "RGHT"):
            return True
        try:
            if upper.startswith(("H:", "HEADING:", "V:", "SPEED:")):
                return float(text.split(":", 1)[1]) == float(text.split(":", 1)[1])
            if upper.startswith(("F:", "B:", "FWD:", "BACK:")):
                return int(float(text.split(":", 1)[1])) >= 0
        except Exception:
            return False
        return False

    def _handle_control_command(self, payload, reply_dst, mesh):
        text = str(payload or "").strip()
        if not self._validate_control_command(text):
            self._reply(reply_dst, "ERROR:CTRL:{0}".format(text), mesh)
            return
        print("endpoint ctrl cmd='{0}'".format(text))
        self._reply(reply_dst, "ACK:CTRL:{0}".format(text), mesh)

    def _handle_debug_command(self, payload, reply_dst, mesh):
        parts = payload.split(":")
        if len(parts) < 3: self._reply(reply_dst, "ERROR:DEBUG:BAD_FORMAT", mesh); return
        action = parts[2]
        if action == "ON":
            if len(parts) > 3:
                try: self.debug_target = int(parts[3])
                except ValueError: self._reply(reply_dst, "ERROR:DEBUG:BAD_TARGET", mesh); return
            self.debug_enabled = True
            self._last_debug_s = time.monotonic() - ENDPOINT_DEBUG_INTERVAL_S
            self._reply(reply_dst, "ACK:DEBUG:ON:{0}".format(self.debug_target), mesh)
        elif action == "OFF":
            self.debug_enabled = False
            self._reply(reply_dst, "ACK:DEBUG:OFF", mesh)
        elif action == "STATUS":
            self._reply(reply_dst, "DEBUG:{0}:{1}".format(
                "ON" if self.debug_enabled else "OFF", self.debug_target), mesh)
        else:
            self._reply(reply_dst, "ERROR:DEBUG:BAD_ACTION", mesh)

    def _reply(self, reply_dst, payload, mesh):
        if int(reply_dst) == int(mesh.node_id): print(payload); return
        mesh.send_data(reply_dst, payload, allow_dtn=False)

class RelayEndpoint(BaseEndpoint):
    def on_data(self, packet, mesh):
        print("DELIVER R N{0}→N{1} '{2}'".format(packet.src, packet.dst, packet.payload))

# ═══════════════════════════════════════════════════════════════════════════════
# ACTUATORS (from hardware/actuators.py)
# ═══════════════════════════════════════════════════════════════════════════════

class PwmServoActuator:
    def __init__(self, pin_name="D7", min_us=500, max_us=2500, frequency=50):
        import board
        import pwmio
        self.pin_name = str(pin_name)
        self.min_us = int(min_us); self.max_us = int(max_us)
        self.frequency = int(frequency)
        pin = getattr(board, self.pin_name)
        self._period_us = 1000000 // self.frequency
        self._pwm = pwmio.PWMOut(pin, frequency=self.frequency, duty_cycle=0)
        self.angle = None

    def move_angle(self, angle, min_angle=0, max_angle=180):
        angle = max(float(min_angle), min(float(max_angle), float(angle)))
        pulse_us = self.min_us + (angle / 180.0) * (self.max_us - self.min_us)
        self._pwm.duty_cycle = int(pulse_us / self._period_us * 65535)
        self.angle = angle
        return angle

    def deinit(self): self._pwm.deinit()

# ═══════════════════════════════════════════════════════════════════════════════
# HARDWARE PLATFORM (from hardware/base.py)
# ═══════════════════════════════════════════════════════════════════════════════

class LoraKeys:
    SCK="sck"; MISO="miso"; MOSI="mosi"; RST="rst"
    NSS="nss"; BUSY="busy"; DIO1="dio1"; RF_SW="rf_sw"

class HardwarePlatform:
    def __init__(self, group_id, node_id, freq_base=900.0, freq_step=1.0):
        self.group_id = int(group_id); self.node_id = node_id
        self.freq_base = float(freq_base); self.freq_step = float(freq_step)
        self.lora = None; self.spi = None; self.led = None
        self.rf_switch = None; self._serial_input_buffer = ""
        self._pins = {}; self.ble = None; self.advertisement = None

    def getIdentifier(self):
        return "G{0}N{1}".format(self.group_id, self.node_id)

    @property
    def frequency_mhz(self):
        return self.freq_base + (self.group_id - 1) * self.freq_step

    @property
    def board_name(self):
        raise NotImplementedError

    @property
    def ble_name(self):
        return self.getIdentifier()

    def setup_pins(self):
        raise NotImplementedError

    def setup_leds(self): return False

    def setup_lora(self, bw=125.0, sf=7, cr=5, useRegulatorLDO=True,
                   tcxoVoltage=1.8, power=22, debug=False):
        import busio
        import digitalio
        from sx1262 import SX1262
        if not self._pins:
            print("No pins set up!"); return False
        self.rf_switch = digitalio.DigitalInOut(self._pins[LoraKeys.RF_SW])
        self.rf_switch.direction = digitalio.Direction.OUTPUT
        self.rf_switch.value = False
        self.spi = busio.SPI(self._pins[LoraKeys.SCK],
                             self._pins[LoraKeys.MOSI],
                             self._pins[LoraKeys.MISO])
        try:
            self.lora = SX1262(self.spi,
                self._pins[LoraKeys.SCK], self._pins[LoraKeys.MOSI],
                self._pins[LoraKeys.MISO], self._pins[LoraKeys.NSS],
                self._pins[LoraKeys.DIO1], self._pins[LoraKeys.RST],
                self._pins[LoraKeys.BUSY], rf_sw=self.rf_switch)
        except TypeError:
            self.lora = SX1262(self.spi,
                self._pins[LoraKeys.SCK], self._pins[LoraKeys.MOSI],
                self._pins[LoraKeys.MISO], self._pins[LoraKeys.NSS],
                self._pins[LoraKeys.DIO1], self._pins[LoraKeys.RST],
                self._pins[LoraKeys.BUSY])
        self.lora.begin(freq=self.frequency_mhz, bw=bw, sf=sf, cr=cr,
                        useRegulatorLDO=useRegulatorLDO, tcxoVoltage=tcxoVoltage,
                        power=power, debug=debug)
        if hasattr(self.lora, "recv_start"): self.lora.recv_start()
        print("lora ok  {0} MHz  SF{1}".format(self.frequency_mhz, sf))
        return True

    def build_endpoint_capabilities(self, runtime_config=None):
        capabilities = {}
        actuator = ENDPOINT_ACTUATOR
        if actuator == "pwm_servo" and ENDPOINT_ENABLE_PWM_SERVO:
            try:
                capabilities["servo"] = PwmServoActuator(
                    pin_name=ENDPOINT_SERVO_PIN,
                    min_us=ENDPOINT_SERVO_MIN_US,
                    max_us=ENDPOINT_SERVO_MAX_US)
            except Exception as e:
                print("endpoint servo unavailable: {0}".format(e))
        return capabilities

    def set_radio_tx_mode(self):
        if self.rf_switch is not None: self.rf_switch.value = True

    def set_radio_rx_mode(self):
        if self.rf_switch is not None: self.rf_switch.value = False

    def read_serial_line(self):
        try:
            import supervisor
            available = int(getattr(supervisor.runtime, "serial_bytes_available", 0))
            if available <= 0: return None
            chunk = sys.stdin.read(available)
            if not chunk: return None
            self._serial_input_buffer += str(chunk)
            if "\n" not in self._serial_input_buffer and "\r" not in self._serial_input_buffer:
                return None
            line = self._serial_input_buffer.replace("\r", "").replace("\n", "").strip()
            self._serial_input_buffer = ""
            return line if line else None
        except Exception: return None

    def blink(self, times=1, on_s=0.05, off_s=0.05): return False

# ═══════════════════════════════════════════════════════════════════════════════
# ESP32-S3 HARDWARE (from hardware/esp32_sx1262.py)
# ═══════════════════════════════════════════════════════════════════════════════

class ESP32SX1262Hardware(HardwarePlatform):
    def __init__(self, group_id, node_id, freq_base=900.0, freq_step=1.0):
        super().__init__(group_id, node_id, freq_base=freq_base, freq_step=freq_step)

    @property
    def board_name(self): return "esp32_sx1262"

    def setup_pins(self):
        import board
        import microcontroller
        self._pins = {
            LoraKeys.SCK:  board.D8,  LoraKeys.MISO: board.D9,
            LoraKeys.MOSI: board.D10, LoraKeys.RST:  board.D1,
            LoraKeys.NSS:  microcontroller.pin.GPIO41,
            LoraKeys.BUSY: microcontroller.pin.GPIO40,
            LoraKeys.DIO1: microcontroller.pin.GPIO39,
            LoraKeys.RF_SW: microcontroller.pin.GPIO38,
        }
        return True

# ═══════════════════════════════════════════════════════════════════════════════
# NRF52840 HARDWARE (from hardware/nrf52840_sx1262.py)
# ═══════════════════════════════════════════════════════════════════════════════

class NRF52840SX1262Hardware(HardwarePlatform):
    def __init__(self, group_id, node_id, freq_base=900.0, freq_step=1.0):
        super().__init__(group_id, node_id, freq_base=freq_base, freq_step=freq_step)

    @property
    def board_name(self): return "nrf52840_sx1262"

    def setup_pins(self):
        import board
        self._pins = {
            LoraKeys.SCK:  board.D8,  LoraKeys.MISO: board.D9,
            LoraKeys.MOSI: board.D10, LoraKeys.NSS:  board.D4,
            LoraKeys.RST:  board.D2,  LoraKeys.BUSY: board.D3,
            LoraKeys.DIO1: board.D1,  LoraKeys.RF_SW: board.D5,
        }
        return True

    def setup_leds(self):
        try:
            import board
            import digitalio
            led_pin = getattr(board, "LED_BLUE", None) or getattr(board, "LED", None)
            if led_pin is None:
                return False
            self.led = digitalio.DigitalInOut(led_pin)
            self.led.direction = digitalio.Direction.OUTPUT
            self.led.value = True
            return True
        except Exception as e:
            print("led unavailable: {0}".format(e))
            self.led = None
            return False

    def blink(self, times=1, on_s=0.05, off_s=0.05):
        if self.led is None: return False
        for _ in range(int(times)):
            self.led.value = False; time.sleep(float(on_s))
            self.led.value = True;  time.sleep(float(off_s))
        return True

# ═══════════════════════════════════════════════════════════════════════════════
# BLE GATEWAY (from software/gateway/ble_gateway.py)
# ═══════════════════════════════════════════════════════════════════════════════

class BleGateway:
    def __init__(self, group_id, node_id):
        self.group_id = int(group_id); self.node_id = int(node_id)
        self.ble = None; self.service = None; self.advertisement = None
        self.ok = False
        self._init_ble()

    def _init_ble(self):
        try:
            import adafruit_ble
            from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
            from adafruit_ble.characteristics import Characteristic
            from adafruit_ble.services import Service
            from adafruit_ble.uuid import VendorUUID
            gid_hex = "{0:02x}".format(self.group_id)

            class MeshService(Service):
                uuid = VendorUUID("13172b58-{0}40-4150-b42d-22f30b0a0499".format(gid_hex))
                cmd_rx = Characteristic(
                    uuid=VendorUUID("13172b58-{0}41-4150-b42d-22f30b0a0499".format(gid_hex)),
                    properties=(Characteristic.WRITE | Characteristic.WRITE_NO_RESPONSE),
                    max_length=BLE_NOTIFY_MAX_LEN)
                data_tx = Characteristic(
                    uuid=VendorUUID("13172b58-{0}42-4150-b42d-22f30b0a0499".format(gid_hex)),
                    properties=(Characteristic.READ | Characteristic.NOTIFY),
                    max_length=BLE_NOTIFY_MAX_LEN)

            self.ble = adafruit_ble.BLERadio()
            self.ble.name = "{0}{1}".format(BLE_NAME_PREFIX, self.group_id)
            self.service = MeshService()
            self.advertisement = ProvideServicesAdvertisement(self.service)
            self.ok = True
        except Exception as e:
            print("ble unavailable: {0}".format(e))
            self.ok = False

    @property
    def connected(self):
        return bool(self.ok and self.ble.connected)

    def start(self):
        if self.ok and not self._is_advertising():
            self.ble.start_advertising(self.advertisement)

    def stop(self):
        if self.ok and self._is_advertising():
            self.ble.stop_advertising()

    def _is_advertising(self):
        adv = getattr(self.ble, "advertising", False)
        if callable(adv):
            try: return bool(adv())
            except Exception: return False
        return bool(adv)

    def notify(self, msg):
        if not self.connected: return
        try:
            self.service.data_tx = str(msg).encode("utf-8")[:BLE_NOTIFY_MAX_LEN]
        except Exception: pass

    def read_command(self):
        if not self.connected: return None
        try:
            value = self.service.cmd_rx
            if value and len(value) > 0:
                self.service.cmd_rx = b""
                return value.decode("utf-8", "ignore").strip().replace("\x00", "")
        except Exception as e:
            print("ble cmd err: {0}".format(e))
        return None
