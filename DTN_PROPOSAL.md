# DTN Store-Carry-Forward Proposal

## Motivation

Current mesh flooding works well when all nodes are reachable. When a destination is
temporarily out of range — or when a relay node hasn't heard a route yet — the packet
is dropped. A DTN (Delay-Tolerant Networking) layer lets a node **hold the message and
deliver it when conditions improve**, instead of failing immediately.

This is valuable even for stationary nodes. A node that just powered on hasn't heard
any route advertisements yet. A node at the edge of range sees intermittent links.
Store-carry-forward bridges those gaps without needing ACKs or two-way handshakes.

---

## Design

### Message Queue

Each node maintains a small outbound queue in RAM:

```python
# In mesh_common.py
_dtn_queue = []
# Each entry: {'src': int, 'dst': int, 'mid': int, 'ttl': int,
#              'payload': str, 'born': float, 'tries': int, 'next_try': float}

DTN_QUEUE_MAX   = 8     # drop oldest when full
DTN_TTL_S       = 120   # wall-clock lifetime (s) — independent of hop TTL
DTN_BASE_RETRY  = 5.0   # first retry after 5 s
DTN_BACKOFF     = 2.0   # multiply per attempt: 5, 10, 20, 40 s...
DTN_MAX_TRIES   = 5     # give up after this many attempts
```

A message is enqueued when:
- `route_next_hop(dst)` returns `None` (no route yet), or
- `send_lbt()` returns `False` (channel busy / TX failed).

---

### Delivery Gating

Before retrying, check two conditions:

1. **Route exists**: `route_next_hop(dst) is not None` (or `dst == 0` for broadcast).
2. **Channel quality**: instantaneous RSSI above a threshold.

```python
RSSI_GATE = -100  # dBm — skip TX if ambient noise floor too high
```

`lora.getRSSIInst()` (already in the driver) gives ambient RSSI without receiving a
packet. If it's worse than `RSSI_GATE`, defer — channel is noisy and TX would likely
fail anyway.

For broadcasts (`dst == 0`), skip the route check; only gate on channel quality.

---

### Retry Loop

Called from the main periodic tick (e.g. every 1 s):

```python
def dtn_tick(lora):
    now = time.monotonic()
    keep = []
    for msg in _dtn_queue:
        age = now - msg['born']
        if age > DTN_TTL_S or msg['tries'] >= DTN_MAX_TRIES:
            print("DTN drop mid={} dst={} age={:.0f}s tries={}".format(
                msg['mid'], msg['dst'], age, msg['tries']))
            continue  # expire
        if now < msg['next_try']:
            keep.append(msg)
            continue  # not yet
        nh = route_next_hop(msg['dst']) if msg['dst'] != 0 else 0
        if nh is None:
            msg['tries'] += 1
            msg['next_try'] = now + DTN_BASE_RETRY * (DTN_BACKOFF ** msg['tries'])
            keep.append(msg)
            continue  # no route yet
        ambient = lora.getRSSIInst()
        if ambient < RSSI_GATE:
            msg['next_try'] = now + 2.0  # short defer, channel noisy
            keep.append(msg)
            continue
        # Conditions met — transmit
        pkt = encode_data(msg['src'], msg['dst'], nh, msg['mid'], msg['ttl'], msg['payload'])
        if lora.send_lbt(pkt, max_tries=3, base_backoff_ms=20):
            lora.recv_start()
            print("DTN deliver mid={} dst={} try={}".format(msg['mid'], msg['dst'], msg['tries']))
        else:
            msg['tries'] += 1
            msg['next_try'] = now + DTN_BASE_RETRY * (DTN_BACKOFF ** msg['tries'])
            keep.append(msg)
    _dtn_queue[:] = keep

def dtn_enqueue(src, dst, mid, ttl, payload):
    now = time.monotonic()
    if len(_dtn_queue) >= DTN_QUEUE_MAX:
        _dtn_queue.pop(0)  # drop oldest
    _dtn_queue.append({
        'src': src, 'dst': dst, 'mid': mid, 'ttl': ttl,
        'payload': payload, 'born': now, 'tries': 0, 'next_try': now + DTN_BASE_RETRY
    })
    print("DTN enqueue mid={} dst={}".format(mid, dst))
```

---

### Integration in Node Files

In `send_data()`, replace the hard `return False` on no-route with enqueue:

```python
def send_data(dst, payload):
    global my_msg_id
    my_msg_id = (my_msg_id + 1) % 256
    mc.data_mark(NODE_ID, my_msg_id)
    nh = 0 if dst == 0 else mc.route_next_hop(dst)
    if dst != 0 and nh is None:
        mc.dtn_enqueue(NODE_ID, dst, my_msg_id, mc.TTL_DEFAULT, payload)
        return False  # will be sent later
    pkt = mc.encode_data(NODE_ID, dst, nh, my_msg_id, mc.TTL_DEFAULT, payload)
    if not lora.send_lbt(pkt, max_tries=3, base_backoff_ms=20):
        mc.dtn_enqueue(NODE_ID, dst, my_msg_id, mc.TTL_DEFAULT, payload)
        return False
    lora.recv_start()
    return True
```

In `_periodic()`, add:

```python
mc.dtn_tick(lora)
```

---

### Route-Triggered Flush

When `route_update()` installs a **new** route (`improved=True`), immediately wake any
queued messages destined for that node by setting `next_try = now`:

```python
def route_update(orig, fwd, adv_hops, link_rssi=None):
    ...
    if total < exist_hops or ...:
        route_table[orig] = {...}
        _dtn_wake(orig)   # flush queue entries for this dest
        return True
    return False

def _dtn_wake(dst):
    now = time.monotonic()
    for msg in _dtn_queue:
        if msg['dst'] == dst:
            msg['next_try'] = now  # deliver on next tick
```

This gives near-instant delivery the moment a route is learned, without waiting for
the next backoff window.

---

## Tradeoffs

| Aspect | Notes |
|--------|-------|
| RAM | 8 messages × ~100 bytes ≈ 800 bytes — acceptable on CircuitPython heap |
| Latency | First retry at 5 s; falls to near-zero once route is known via wake |
| Duplicate risk | `mid` dedup cache still filters replays after delivery |
| CircuitPython | No threads — `dtn_tick()` runs in main loop, non-blocking |
| No persistence | Queue lost on reset; acceptable for chat-style messages |

---

## Why This Works Even for Stationary Nodes

Stationary doesn't mean always-connected. A node that just booted has an empty routing
table. Without DTN it silently drops the first few seconds of traffic. With DTN, those
messages sit in queue for ≤5 s and deliver automatically once the first ROUTE_AD
propagates. No user retry needed, no lost messages at startup.
