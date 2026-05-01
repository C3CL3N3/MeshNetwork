# SPDX-FileCopyrightText: 2026 Student Lab - COMP 4531 - HKUST
# SPDX-License-Identifier: MIT
#
# mesh_common.py — Shared protocol logic for all mesh nodes.
#
# Packet formats:
#   H:<src>                                        HELLO      (10 s)
#   R:<orig>:<fwd>:<mid>:<hops>                    ROUTE_AD   (flooded, 30 s)
#   D:<src>:<dst>:<next_hop>:<mid>:<ttl>:<payload> DATA       (routed)

import time

# ── Protocol parameters ───────────────────────────────────────────────────────
SF               = 7    # fixed for all nodes
TTL_DEFAULT      = 6
ROUTE_TTL        = 5    # max hops a ROUTE_AD propagates
NEIGHBOR_EXPIRE  = 120  # s
ROUTE_EXPIRE     = 90   # s
HELLO_INTERVAL   = 10   # s
ROUTE_AD_INTERVAL = 30  # s
CACHE_SIZE       = 60

# ── Dedup caches ──────────────────────────────────────────────────────────────
_data_cache  = []
_route_cache = []

def data_seen(src, mid):   return (src, mid) in _data_cache
def route_seen(orig, mid): return (orig, mid) in _route_cache

def data_mark(src, mid):
    _data_cache.append((src, mid))
    if len(_data_cache) > CACHE_SIZE:
        _data_cache.pop(0)

def route_mark(orig, mid):
    _route_cache.append((orig, mid))
    if len(_route_cache) > CACHE_SIZE:
        _route_cache.pop(0)

# ── Neighbor table ────────────────────────────────────────────────────────────
neighbor = {}
# {node_id: {'snr': float, 'rssi': int, 'seen': float}}

def neighbor_update(src, snr, rssi):
    neighbor[src] = {'snr': snr, 'rssi': rssi, 'seen': time.monotonic()}

def neighbor_expire():
    now  = time.monotonic()
    dead = [k for k, v in neighbor.items() if now - v['seen'] > NEIGHBOR_EXPIRE]
    for k in dead:
        del neighbor[k]
    return dead

# ── Routing table ─────────────────────────────────────────────────────────────
route_table = {}
# {dest_id: {'next_hop': int, 'hops': int, 'seen': float}}

def route_update(orig, fwd, adv_hops):
    """Bellman-Ford: prefer fewer hops. Returns True if route improved."""
    existing = route_table.get(orig, {}).get('hops', 9999)
    total    = adv_hops + 1
    if total < existing:
        route_table[orig] = {'next_hop': fwd, 'hops': total, 'seen': time.monotonic()}
        return True
    return False

def route_expire():
    now  = time.monotonic()
    dead = [k for k, v in route_table.items() if now - v['seen'] > ROUTE_EXPIRE]
    for k in dead:
        del route_table[k]
    return dead

def route_next_hop(dst):
    r = route_table.get(dst)
    return r['next_hop'] if r else None

# ── Packet encode / decode ────────────────────────────────────────────────────

def encode_hello(src):
    return "H:{}".format(src).encode()

def decode_hello(raw):
    """Returns src or None."""
    try:
        s = raw.decode('utf-8', 'ignore').strip()
        if not s.startswith("H:"):
            return None
        return int(s[2:])
    except Exception:
        return None

def encode_route_ad(orig, fwd, mid, hops):
    return "R:{}:{}:{}:{}".format(orig, fwd, mid, hops).encode()

def decode_route_ad(raw):
    """Returns (orig, fwd, mid, hops) or None."""
    try:
        s = raw.decode('utf-8', 'ignore').strip()
        if not s.startswith("R:"):
            return None
        p = s[2:].split(":")
        if len(p) != 4:
            return None
        return int(p[0]), int(p[1]), int(p[2]), int(p[3])
    except Exception:
        return None

def encode_data(src, dst, next_hop, mid, ttl, payload):
    return "D:{}:{}:{}:{}:{}:{}".format(src, dst, next_hop, mid, ttl, payload).encode()

def decode_data(raw):
    """Returns (src, dst, next_hop, mid, ttl, payload) or None."""
    try:
        s = raw.decode('utf-8', 'ignore').strip()
        if not s.startswith("D:"):
            return None
        p = s[2:].split(":", 5)
        if len(p) != 6:
            return None
        return int(p[0]), int(p[1]), int(p[2]), int(p[3]), int(p[4]), p[5]
    except Exception:
        return None
