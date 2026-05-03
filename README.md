# LoRa Mesh Network

**COMP 4531 — IoT and Smart Sensing | HKUST**

Distance-vector LoRa mesh network for Seeed XIAO boards. Nodes discover each other, build routing tables, and forward unicast or broadcast packets autonomously. A Web Bluetooth dashboard visualises the live topology, shows per-link RSSI, and lets you send messages across the network. Firmware is flashed directly from the browser.

---

## Hardware

| Board | Role | Node ID |
|-------|------|---------|
| Seeed XIAO nRF52840 Sense + Wio-SX1262 | BLE gateway — bridges mesh to browser | 1 (fixed) |
| Seeed XIAO ESP32-S3 + Wio-SX1262 | LoRa relay node | 2 – 7 |

The nRF is the only BLE-capable board; all others are pure LoRa relays. Every node participates equally in routing and relaying — the nRF is not a hub.

---

## Radio Parameters

| Parameter | Value |
|-----------|-------|
| Frequency | 912.0 MHz |
| Bandwidth | 125 kHz |
| Spreading Factor | SF7 (fixed) |
| Coding Rate | 4/5 |
| TX Power | 22 dBm |
| Oscillator | Crystal @ 0 V (nRF) · TCXO @ 1.8 V (ESP32) |

SF7 gives ~7–8 ms airtime per packet. All nodes must share the same `MESH_FREQ`, `SF`, `BW`, and `CR`.

---

## Protocol

Three packet types, ASCII-encoded, transmitted as UTF-8 over LoRa.

### HELLO — `H:<src>`
Broadcast every **10 s**. One-hop only (never relayed). Populates the neighbor table with RSSI and SNR. Neighbor entries expire after **120 s**.

### ROUTE_AD — `R:<orig>:<fwd>:<mid>:<hops>`
Flooded every **30 s** per node (origin advertises itself at `hops=0`). Each receiving node increments `hops` and re-broadcasts if `hops < ROUTE_TTL (5)`, with a 20–120 ms random jitter. Deduplication via `(orig, mid)` cache (60 entries).

Routing table is built with **Bellman-Ford**: fewer hops wins; equal hops → better link RSSI wins. Route entries expire after **90 s**.

### DATA — `D:<src>:<dst>:<next_hop>:<mid>:<ttl>:<payload>`
TTL starts at **6**. Two forwarding modes:

- **Unicast** (`dst ≠ 0`, `next_hop ≠ 0`): only the node matching `next_hop` relays, looking up its own route table to find the next hop toward `dst`.
- **Flood** (`dst = 0` or `next_hop = 0`): all nodes probabilistically relay. Relay probability decreases with stronger RSSI (strong signal = many nodes heard it = less need to relay individually: 40% at RSSI > −60 dBm, up to 97% at RSSI < −90 dBm).

Random jitter 50–200 ms before relay. LBT (Listen-Before-Talk) with 3 retries on all relayed packets.

### DTN Store-Carry-Forward
When a unicast packet arrives with no route to the destination, it is queued locally:

- **Hold time:** 30 s max
- **Retry interval:** 3 s
- **Queue capacity:** 16 packets (FIFO eviction)
- **Route-triggered flush:** when a new route to `dst` appears, queued packets drain immediately on the next tick

---

## Repository Structure

```
├── code_nrf.py                  # nRF52840 — BLE gateway + mesh node
├── code_esp32.py                # ESP32-S3 — LoRa relay node
├── COMP4531_Dash-main/
│   ├── index.html               # Web dashboard (3 tabs: connect · mesh · serial)
│   ├── script.js                # BLE core, mesh viz (D3), serial parser, flash logic
│   ├── style.css                # Dark-theme UI
│   ├── mesh_common.py           # Shared protocol: encode/decode, routing, DTN
│   ├── sx1262.py                # SX1262 CircuitPython driver (async RX, LBT, CAD)
│   └── code_esp32.py            # Copy flashed to relay nodes via browser
└── DTN_PROPOSAL.md              # DTN design document
```

---

## Setup

### 1 — CircuitPython Libraries

Install on each board's `lib/` folder via the CIRCUITPY drive:

**nRF52840:**
- `adafruit_ble` (full bundle)

**Both boards:**
- `sx1262.py` and `mesh_common.py` are flashed automatically by the dashboard

### 2 — Set NODE_ID

| File | Variable | Value |
|------|----------|-------|
| `code_nrf.py` | `NODE_ID` | `1` (do not change) |
| `code_esp32.py` | `NODE_ID` | `2` through `7` (unique per board) |
| both | `GROUP_ID` | `13` (must match across all nodes) |

### 3 — Flash Firmware

**Option A — Browser flash (recommended):**
1. Open `COMP4531_Dash-main/index.html` in Chrome (file:// works — do **not** use Live Server)
2. Connect the board via USB while in bootloader/CIRCUITPY mode
3. In the **connect** tab: pick the node ID (1–7), select the board type, click **flash nrf52840** or **flash esp32_s3**
4. The dashboard fetches `code.py`, `mesh_common.py`, `sx1262.py` and writes them to the CIRCUITPY drive — board restarts automatically

**Option B — Manual:**
Copy `code_nrf.py` → `code.py` and `mesh_common.py`, `sx1262.py` to the CIRCUITPY root.

### 4 — Connect Dashboard

1. Open `index.html` directly in Chrome (`file://`) — Web Bluetooth requires no server, but does require Chrome or Edge
2. **Connect tab:** enter Group ID (13), click **connect** — Chrome scans for `MESH_G13`
3. **Mesh tab:** live force-directed topology appears as nodes are discovered
4. **Serial tab:** connect an ESP32 via USB — real-time serial monitor + per-node chat

> **Do not use VS Code Live Server** — it injects a file-watcher script that reloads the page on every save.

---

## Dashboard

Three tabs:

### connect
- BLE pair with the nRF52840 gateway
- Status dot: grey (disconnected) · green (connected) · yellow (reconnecting)
- Auto-reconnect with exponential backoff (1 s → 2 s → 5 s → 10 s → 15 s)
- Firmware flash panel: pick node ID (1–7), board type (standard / servo), flash directly to CIRCUITPY
- Persistent drive handles via IndexedDB — picks the right drive automatically after first flash

### mesh
- **Force-directed D3 graph:** gateway pinned at center, relay nodes orbiting by hop count
- **Node circles:** dark fill = gateway, white fill = relay; label `N<id>`, sublabel RSSI or hop count
- **Links:** RSSI-coloured (green > −70 dBm · orange > −90 dBm · red below); dashed = multi-hop inferred route
- **Animated particles:** moving along links when packets travel
- **Topology source:** BLE notifications (`MESH_NB`, `MESH_ROUTE`, `MESH_RX`) when connected via BLE; OR parsed serial output when connected via serial tab
- **Serial viz parsing:** `RX H` → direct link; `RX R [NEW]` → route; `TX H` → identifies monitored node
- **Node list** (sidebar): all discovered nodes with RSSI or hop distance and last-seen age
- **Send:** broadcast or unicast message to any discovered node

### serial
- Web Serial connection to any ESP32 relay node via USB
- Per-node conversation sidebar (one chat pane per discovered node + broadcast)
- Raw serial terminal at the bottom
- Same `TO:<dst>:<text>` protocol as firmware serial interface
- All received lines are also fed into mesh viz (parallel with BLE path)

---

## BLE Interface

Service UUID derived from GROUP_ID. Example for group 13 (`0d` hex):

```
Service:  13172b58-0d40-4150-b42d-22f30b0a0499
Write:    13172b58-0d41-4150-b42d-22f30b0a0499  (commands, max 100 bytes)
Notify:   13172b58-0d42-4150-b42d-22f30b0a0499  (events, max 100 bytes)
```

**Commands (central → gateway):**

| Command | Effect |
|---------|--------|
| `SEND_MESH:<text>` | Broadcast from gateway |
| `SEND_NODE:<dst>:<text>` | Unicast to node `dst` |
| `PARROT:<text>` | BLE echo test |
| `ROUTES` | Dump routing table as `MESH_ROUTE` notifications |
| `NEIGHBORS` | Dump neighbor table as `MESH_NB` notifications |

**Notifications (gateway → central):**

| Notification | Meaning |
|-------------|---------|
| `MESH_INFO:NODE_ID:<n>` | Gateway real NODE_ID (sent 1.5 s after connect) |
| `MESH_PING:<n>` | Keepalive every 5 s |
| `MESH_RX:<src>\|<dst>\|<mid>\|<ttl>\|<rssi>\|<snr>\|<payload>` | Packet received |
| `MESH_TX:<src>\|<dst>\|<nh>\|<mid>\|<ttl>\|<payload>` | Packet sent |
| `MESH_ROUTE:<dest>\|<next_hop>\|<hops>` | Route discovered or dump entry |
| `MESH_NB:<node>\|<rssi>\|<snr>` | Neighbor update or dump entry |
| `MESH_ERR:LORA_FAIL` | LoRa hardware not available |
| `MESH_ERR:NO_ROUTE:<dst>` | No route — packet queued in DTN |

---

## Serial Interface (both boards)

| Input | Action |
|-------|--------|
| `<text>` + Enter | Broadcast: `[NODE_ID] text` |
| `TO:<dst>:<text>` + Enter | Unicast to node `dst`: `[NODE_ID] text` |

nRF serial also shows BLE state (`advertising`, `ble connected`, `ble disconnected`). If `adafruit_ble` is missing from the nRF lib folder, the board falls back to serial+LoRa only mode and prints `ble unavailable — running serial+lora only`.

---

## Known Limitations

| Issue | Notes |
|-------|-------|
| No delivery ACK | Use `PARROT:<tag>` → `PONG:<n>:<tag>` as manual round-trip test |
| 8-bit `mid` wraps at 256 | Dedup cache (60 entries) bounds false-positive window; not an issue at low traffic |
| Hop-count metric only | RSSI tiebreaker applies to last-hop link only, not full path quality |
| Routes linger up to 90 s after node failure | No explicit route-error packet; expiry is the only mechanism |
| BLE MTU 100 bytes | Payloads > ~90 bytes after headers are silently truncated |
| Mesh diameter capped at 5 relay hops | Increase `ROUTE_TTL` in `mesh_common.py` for larger networks |
| Single frequency, no channel hopping | All nodes share 912 MHz; SF7 short airtime reduces collision window |

---

## License

MIT
