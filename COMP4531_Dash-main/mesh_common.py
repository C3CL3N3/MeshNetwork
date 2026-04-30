# SPDX-FileCopyrightText: 2026 Student Lab - COMP 4531 - HKUST
# SPDX-License-Identifier: MIT
#
# mesh_common.py — Shared protocol logic for all mesh nodes.
# Import as: import mesh_common as mc
#
# Packet formats:
#   H:<src>:<sf>                                   HELLO      (not relayed, 10 s)
#   R:<orig>:<fwd>:<mid>:<hops>:<cost>             ROUTE_AD   (flooded, 30 s)
#   D:<src>:<dst>:<next_hop>:<mid>:<ttl>:<payload> DATA       (routed by next_hop)
#
# network_sf is a module-level variable. Node files read/trigger changes via:
#   mc.network_sf                   — current operating SF (all nodes same value)
#   mc.network_sf_check_up()        — escalate if any link degraded
#   mc.network_sf_check_down(t)     — de-escalate after sustained good links

import time

# ── SF parameters ─────────────────────────────────────────────────────────────
SF_MIN = 7
SF_MAX = 12
SF_DEFAULT = 7

# Approximate airtime (ms) for a ~20-byte payload at 125 kHz BW, CR 4/5
SF_AIRTIME = {7: 41, 8: 72, 9: 144, 10: 289, 11: 577, 12: 1154}

# Step UP (worse SF) if measured SNR drops below this — 5 dB above raw minimum
SF_HOLD = {7: -2.5, 8: -5.0, 9: -7.5, 10: -10.0, 11: -12.5, 12: -99.0}
# Step DOWN (better SF) if measured SNR stays above this — same 5 dB cushion
SF_DOWN = {8: 5.0, 9: 2.5, 10: 0.0, 11: -2.5, 12: -5.0}

SF_DOWN_HOLD_S = 60  # s all links must stay good before stepping SF down

# ── Protocol parameters ───────────────────────────────────────────────────────
ROUTE_TTL         = 5    # max hops a ROUTE_AD propagates
TTL_DEFAULT       = 6    # starting TTL for DATA packets
NEIGHBOR_EXPIRE   = 120  # s — drop neighbor if no HELLO received
ROUTE_EXPIRE      = 90   # s — drop route if no ROUTE_AD refreshed it
INF_COST          = 99999
HELLO_INTERVAL    = 10   # s
ROUTE_AD_INTERVAL = 30   # s
CACHE_SIZE        = 60   # dedup cache depth per table

# ── Shared mutable state ──────────────────────────────────────────────────────
# All nodes converge to the same value independently by reacting to SNR.
network_sf = SF_DEFAULT

# ── Dedup caches ──────────────────────────────────────────────────────────────
_data_cache  = []  # [(src, mid), ...]  — for D packets
_route_cache = []  # [(orig, mid), ...] — for R packets

def data_seen(src, mid):
    return (src, mid) in _data_cache

def data_mark(src, mid):
    _data_cache.append((src, mid))
    if len(_data_cache) > CACHE_SIZE:
        _data_cache.pop(0)

def route_seen(orig, mid):
    return (orig, mid) in _route_cache

def route_mark(orig, mid):
    _route_cache.append((orig, mid))
    if len(_route_cache) > CACHE_SIZE:
        _route_cache.pop(0)

# ── Neighbor table ────────────────────────────────────────────────────────────
# Updated from HELLO (always direct link) and ROUTE_AD fwd field.
# 'sf' here is the minimum SF this link needs for reliable decode, derived from
# SNR measurements. Used as routing cost, independent of network_sf.
neighbor = {}
# {node_id: {'sf': int, 'snr': float, 'rssi': int, 'seen': float}}

def neighbor_update(src, snr, rssi):
    """Update link metrics for src. Returns (old_sf, new_sf)."""
    prev   = neighbor.get(src, {})
    old_sf = prev.get('sf', network_sf)
    new_sf = _link_sf(old_sf, snr)
    neighbor[src] = {'sf': new_sf, 'snr': snr, 'rssi': rssi, 'seen': time.monotonic()}
    return old_sf, new_sf

def _link_sf(cur, snr):
    """Compute minimum SF this SNR reading requires (with 5 dB safety margin)."""
    if cur < SF_MAX and snr < SF_HOLD[cur]:
        return cur + 1
    if cur > SF_MIN and snr > SF_DOWN[cur]:
        return cur - 1
    return cur

def neighbor_expire():
    now  = time.monotonic()
    dead = [k for k, v in neighbor.items() if now - v['seen'] > NEIGHBOR_EXPIRE]
    for k in dead:
        del neighbor[k]
    return dead

# ── Routing table ─────────────────────────────────────────────────────────────
# Bellman-Ford distance-vector. Cost = cumulative SF airtime along path (ms).
# This metric makes the router prefer two short SF7 hops (82 ms) over one long
# SF12 hop (1154 ms) — the core PoC claim.
route_table = {}
# {dest_id: {'next_hop': int, 'hops': int, 'cost': int, 'seen': float}}

def route_update(orig, fwd, adv_hops, adv_cost):
    """
    Bellman-Ford update from a received ROUTE_AD.
    fwd      = immediate transmitter of the R packet (direct link to us).
    adv_hops = hops from fwd back to orig (already accumulated).
    adv_cost = airtime cost from fwd back to orig (already accumulated).
    We add our own link cost (me → fwd) to get total cost.
    Returns True if the route to orig improved.
    """
    nb = neighbor.get(fwd)
    if nb is None:
        return False
    link_cost  = SF_AIRTIME[nb['sf']]
    total_cost = adv_cost + link_cost
    total_hops = adv_hops + 1
    existing   = route_table.get(orig, {}).get('cost', INF_COST)
    if total_cost < existing:
        route_table[orig] = {
            'next_hop': fwd,
            'hops':     total_hops,
            'cost':     total_cost,
            'seen':     time.monotonic(),
        }
        return True
    return False

def route_expire():
    now  = time.monotonic()
    dead = [k for k, v in route_table.items() if now - v['seen'] > ROUTE_EXPIRE]
    for k in dead:
        del route_table[k]
    return dead

def route_next_hop(dst):
    """Return next_hop node_id toward dst, or None if no route."""
    r = route_table.get(dst)
    return r['next_hop'] if r else None

# ── Network-wide SF adaptation ────────────────────────────────────────────────
# All nodes react to their own SNR measurements and converge to the same SF
# independently — no coordinator needed. Escalation is immediate (safety first).
# De-escalation requires SF_DOWN_HOLD_S seconds of sustained good links.

def network_sf_check_up():
    """Escalate network_sf by 1 if any direct link is degraded. Returns True if changed."""
    global network_sf
    if network_sf >= SF_MAX:
        return False
    for nb in neighbor.values():
        if nb['snr'] < SF_HOLD[network_sf]:
            network_sf += 1
            return True
    return False

def network_sf_check_down(good_since):
    """
    De-escalate network_sf after sustained good links.
    good_since: monotonic timestamp when all links last became good, or None.
    Returns (changed: bool, new_good_since).
    """
    global network_sf
    if network_sf <= SF_MIN or not neighbor:
        return False, None
    all_good = all(nb['snr'] > SF_DOWN[network_sf] for nb in neighbor.values())
    if not all_good:
        return False, None              # some link still weak, reset timer
    if good_since is None:
        return False, time.monotonic()  # start hysteresis timer
    if time.monotonic() - good_since >= SF_DOWN_HOLD_S:
        network_sf -= 1
        return True, None               # stepped down, reset timer
    return False, good_since            # timer running, not yet

# ── Packet encode / decode ────────────────────────────────────────────────────

def encode_hello(src, sf):
    return "H:{}:{}".format(src, sf).encode()

def decode_hello(raw):
    """Returns (src, sf) or None."""
    try:
        s = raw.decode('utf-8', 'ignore').strip()
        if not s.startswith("H:"):
            return None
        p = s[2:].split(":")
        if len(p) != 2:
            return None
        return int(p[0]), int(p[1])
    except Exception:
        return None

def encode_route_ad(orig, fwd, mid, hops, cost):
    return "R:{}:{}:{}:{}:{}".format(orig, fwd, mid, hops, cost).encode()

def decode_route_ad(raw):
    """Returns (orig, fwd, mid, hops, cost) or None."""
    try:
        s = raw.decode('utf-8', 'ignore').strip()
        if not s.startswith("R:"):
            return None
        p = s[2:].split(":")
        if len(p) != 5:
            return None
        return int(p[0]), int(p[1]), int(p[2]), int(p[3]), int(p[4])
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
        p = s[2:].split(":", 5)  # limit to 5 splits — payload may contain colons
        if len(p) != 6:
            return None
        return int(p[0]), int(p[1]), int(p[2]), int(p[3]), int(p[4]), p[5]
    except Exception:
        return None
