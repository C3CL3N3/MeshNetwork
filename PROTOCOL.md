# LoRa Mesh Network — Protocol Reference & Test Checklist

**COMP 4531 · IoT and Smart Sensing · HKUST**

---

## 1. System Overview

```
[ Browser Dashboard ]
        ↕  Web BLE (two GATT characteristics)
[ nRF52840 — Node 1 ]  ←—LoRa 912 MHz—→  [ ESP32-S3 — Node 2 ]
      BLE Gateway                              Pure LoRa Relay
```

The nRF52840 is the **BLE gateway**: it relays mesh traffic to/from the browser.  
The ESP32-S3 is a **pure LoRa relay**: no BLE, floods packets and sends periodic beacons.

---

## 2. LoRa Mesh Protocol

### Packet format

```
M:<src>:<dst>:<mid>:<ttl>:<payload>
```

| Field     | Type   | Description                                                        |
| --------- | ------ | ------------------------------------------------------------------ |
| `src`     | uint8  | Originating NODE_ID (1–255)                                        |
| `dst`     | uint8  | Destination NODE_ID; **0 = broadcast** (all nodes process payload) |
| `mid`     | uint8  | Per-source message counter, wraps at 256                           |
| `ttl`     | uint8  | Hops remaining; decremented on each relay                          |
| `payload` | string | Arbitrary UTF-8 text (max ~85 chars after header)                  |

### Flooding algorithm

1. A node **originates** a packet by inserting its own `NODE_ID`, the `dst`, and a fresh `mid`, marks `(src, mid)` as seen, and transmits via LoRa.
2. Every node that **receives** a packet with an unseen `(src, mid)` pair:
   - Marks `(src, mid)` seen in the rolling 30-entry dedup cache.
   - If BLE-connected **and** `dst == 0 or dst == NODE_ID`: sends a `MESH_RX:…` notification to the dashboard.
   - If `ttl > 1`: waits `0.05 × (NODE_ID % 5)` seconds (per-node stagger), then retransmits with `ttl − 1`.
3. Duplicate `(src, mid)` pairs are **silently dropped**. This prevents broadcast storms.
4. A packet with `ttl = 1` is **not** relayed further.
5. **Unicast packets are still flooded** — every relay forwards them regardless of `dst`. Only the payload processing (BLE notification) is gated on `dst`.

### Radio parameters

| Parameter        | Value                                |
| ---------------- | ------------------------------------ |
| Frequency        | 912.0 MHz (fixed, same on all nodes) |
| Bandwidth        | 125 kHz                              |
| Spreading Factor | SF 7                                 |
| Coding Rate      | 4/5                                  |
| TX Power         | 22 dBm (ESP32)                       |
| Max hops (TTL)   | 5                                    |

> **RF switch**: the Wio-SX1262 module has an external SPDT RF path switch.  
> It **must** be set `True` before `lora.send()` and back to `False` immediately after,  
> otherwise transmissions are silently lost.

### `lora.recv()` call convention

```python
result = lora.recv(timeout_en=True, timeout_ms=300)
```

Calling `lora.recv()` with no arguments blocks indefinitely.  
`timeout_en=True, timeout_ms=300` makes it return after 300 ms if no packet arrives.

---

## 3. BLE Architecture (nRF52840 only)

Two separate GATT characteristics under a single vendor service:

| Characteristic | UUID suffix | Direction      | Properties               | Purpose                |
| -------------- | ----------- | -------------- | ------------------------ | ---------------------- |
| `cmd_rx`       | `…41…`      | Central → Node | WRITE, WRITE_NO_RESPONSE | Browser sends commands |
| `data_tx`      | `…42…`      | Node → Central | READ, NOTIFY             | Node sends events/data |

Full UUID template: `13172b58-{GID_HEX}{SUFFIX}-4150-b42d-22f30b0a0499`  
where `GID_HEX` = GROUP_ID printed as two hex digits (e.g. GROUP_ID 13 → `0d`).

**Why two characteristics?**  
A single characteristic shared for both WRITE and NOTIFY creates a race condition: the peripheral setting the value for a notification can overwrite a command written by the central before it is processed (and vice versa). Separate characteristics eliminate this entirely.

### BLE command protocol (central → node via `cmd_rx`)

| Command                   | Action                                                          |
| ------------------------- | --------------------------------------------------------------- |
| `SEND_MESH:<text>`        | nRF originates a broadcast (dst=0) LoRa mesh packet             |
| `SEND_NODE:<dst>:<text>`  | nRF originates a unicast LoRa packet addressed to node `<dst>`  |
| `PARROT:<text>`           | nRF immediately echoes `MESH_PARROT:<text>` (BLE loopback test) |

### BLE notification protocol (node → central via `data_tx`)

| Notification                                                  | Meaning                                                        |
| ------------------------------------------------------------- | -------------------------------------------------------------- |
| `MESH_INFO:NODE_ID:<n>`                                       | Sent 1.5 s after BLE connect; tells dashboard the real NODE_ID |
| `MESH_PING:<n>`                                               | Heartbeat, sent every 5 s while connected                      |
| `MESH_RX:<src>\|<dst>\|<mid>\|<ttl>\|<rssi>\|<snr>\|<payload>` | Received a mesh packet (7 pipe-separated fields)               |
| `MESH_TX:<src>\|<dst>\|<mid>\|<ttl>\|<payload>`               | Confirmed a mesh transmission (5 pipe-separated fields)        |
| `MESH_PARROT:<text>`                                          | Echo response to a `PARROT:` command                           |
| `MESH_ERR:LORA_FAIL`                                          | LoRa hardware failed to initialise                             |

---

## 4. Function Reference

### `code_nrf.py`

| Function                                  | Description                                                                                        |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `blink(n)`                                | Blinks the blue LED `n` times (50 ms on / 50 ms off per cycle)                                     |
| `already_seen(src, mid)`                  | Returns `True` if `(src, mid)` is in the dedup cache                                               |
| `mark_seen(src, mid)`                     | Adds `(src, mid)` to the rolling dedup cache; evicts oldest if > 30 entries                        |
| `encode_pkt(src, dst, mid, ttl, payload)` | Returns `b"M:<src>:<dst>:<mid>:<ttl>:<payload>"`                                                   |
| `decode_pkt(raw)`                         | Parses raw bytes; returns `(src, dst, mid, ttl, payload)` tuple or `None`                          |
| `lora_tx(src, dst, mid, ttl, payload)`    | Toggles RF switch, calls `lora.send()`, toggles back                                               |
| `ble_notify(msg)`                         | Writes `msg` to `data_tx` characteristic (triggers BLE notification)                               |
| `lora_rx_and_relay()`                     | Non-blocking receive; deduplicates; notifies BLE central if `dst` matches; relays if `ttl > 1`     |

### `code_esp32.py`

| Function                                  | Description                                                                                        |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `already_seen(src, mid)`                  | Same dedup check as nRF                                                                            |
| `mark_seen(src, mid)`                     | Same rolling cache as nRF                                                                          |
| `encode_pkt(src, dst, mid, ttl, payload)` | Same packet encoder as nRF                                                                         |
| `decode_pkt(raw)`                         | Same packet decoder as nRF                                                                         |
| `lora_send(pkt_bytes)`                    | Toggles RF switch, calls `lora.send()`, toggles back                                               |
| `mesh_send(payload, dst=0)`               | Increments `my_msg_id`, marks seen, calls `lora_send()` with a new origination packet              |

### `script.js` (dashboard)

| Function               | Description                                                                                              |
| ---------------------- | -------------------------------------------------------------------------------------------------------- |
| `connect()`            | Scans for BLE device, gets `writeChar` and `notifyChar`, starts notifications, initialises mesh topology |
| `disconnect()`         | Disconnects GATT                                                                                         |
| `send(cmd)`            | Writes `cmd` to `writeChar` (uses WRITE_NO_RESPONSE if available)                                        |
| `handleControlData(e)` | Routes incoming BLE notifications to the appropriate handler                                             |
| `handleMeshInfo(data)` | Updates `meshMyId` with the node's real NODE_ID                                                          |
| `handleMeshRx(data)`      | Parses 7-field `MESH_RX` notification; updates topology, creates D3 particle, mirrors to LoRa chat      |
| `handleMeshTx(data)`      | Parses 5-field `MESH_TX` notification; logs TX confirmation in the mesh log                             |
| `sendLoRa()`              | Sends LoRa chat input as `SEND_MESH:<text>` (broadcast)                                                 |
| `sendMesh()`              | Reads `#meshDstSelect`; sends `SEND_MESH:` (broadcast) or `SEND_NODE:<dst>:` (unicast)                  |
| `parrotTest()`            | Sends `PARROT:<timestamp>` to test BLE write → notify round-trip                                        |
| `loraParrotTest()`        | Sends `SEND_MESH:PARROT:<timestamp>` to test full LoRa round-trip via ESP32                             |
| `flashDevice(board)`      | Opens file pickers to copy firmware `.py` → `code.py` on CIRCUITPY drive                                |
| `connectSerial()`         | Opens Web Serial port to ESP32; spawns read loop that prints incoming lines                              |
| `disconnectSerial()`      | Closes serial port and writer                                                                            |
| `sendSerial()`            | Writes text from `#serialInput` to the ESP32 serial port (triggers `mesh_send` on the ESP32)            |
| `meshInit()`              | Creates D3 v7 SVG with glow defs, dot background, zoom/pan, force simulation, and animation loop        |
| `meshResize()`            | Recalculates SVG dimensions and re-fixes gateway node at center after window resize                      |
| `meshD3Update()`          | D3 data-join: creates/updates node circles, link lines, RSSI labels, and orbital rings                  |
| `meshD3Tick()`            | Called by D3 simulation on each tick; positions SVG elements from simulation x/y                        |
| `meshAnimLoop()`          | `requestAnimationFrame` loop that animates packet particles along link paths in SVG                      |
| `updateMeshDstSelect()`   | Rebuilds the destination dropdown from the current `meshNodes` map                                       |
| `rssiColor(rssi)`         | Returns green / orange / red depending on signal strength                                               |
| `drawLoraRssiChart()`     | Plots RSSI vs distance on the LoRa tab canvas                                                           |

---

## 5. Test Checklist

### Hardware setup

- [ ] nRF52840 flashed with `code_nrf.py` as `code.py`
- [ ] ESP32-S3 flashed with `code_esp32.py` as `code.py`
- [ ] Both boards set to the **same** `MESH_FREQ` (default `912.0`)
- [ ] `GROUP_ID` on nRF matches the value entered in the dashboard
- [ ] `NODE_ID` is unique per board (`1` for nRF, `2` for ESP32)
- [ ] nRF serial monitor shows `LoRa OK  912.0 MHz  SF7  BW125.0` then `Node 1  912.0 MHz  SF7  TTL=5`
- [ ] ESP32 serial monitor shows `Node 2  912.0 MHz  SF7  TTL=5` and `Mesh relay running...`

### Stage 1 — BLE connectivity

- [ ] Open dashboard in Chrome, enter Group ID, click **Connect** — status dot turns green
- [ ] Within 5 seconds: `♥ heartbeat 1` appears in the terminal (proves BLE notify works)
- [ ] Within 6 seconds: `MESH_INFO` arrives and **My Node** field updates to `Node 1`
- [ ] Click **BLE Parrot** → `✓ BLE parrot OK → "XXXX"` appears within ~1 s
- [ ] nRF serial shows `CMD: PARROT:XXXX` and `PING 1` every 5 s

### Stage 2 — LoRa TX (nRF → air)

- [ ] Send a message from the dashboard LoRa tab
- [ ] nRF serial shows `TX src=1 dst=0 mid=1 ttl=5 '<text>'`
- [ ] `MESH_TX` notification arrives in dashboard → second log entry `→ TX broadcast "<text>"` appears

### Stage 3 — LoRa RX (ESP32 → nRF)

- [ ] Wait up to 30 s for ESP32 beacon — ESP32 serial shows `TX beacon BCN:2`
- [ ] nRF serial shows `RX src=2 mid=1 ttl=5 rssi=… 'BCN:2'`
- [ ] Dashboard Mesh tab shows a new node `N2` appear on the topology canvas
- [ ] Dashboard terminal shows `MESH_RX` entry for `BCN:2`

### Stage 4 — Full round-trip (LoRa Parrot)

- [ ] Click **LoRa Parrot** — nRF serial shows `TX src=1 mid=X ttl=5 'PARROT:XXXX'`
- [ ] ESP32 serial shows `RX src=1 … 'PARROT:XXXX'` and `→ PONG sent for parrot`
- [ ] nRF serial shows `RX src=2 … 'PONG:2:XXXX'`
- [ ] Dashboard Mesh log shows `MESH_RX` from `N2` with payload `PONG:2:XXXX`

### Stage 5 — Mesh relay (multi-hop)

- [ ] Send a message from the dashboard; ESP32 serial shows `RX src=1 … → relayed`
- [ ] TTL in the relayed packet is `original TTL − 1`
- [ ] nRF drops the relay as a duplicate (correct — `(1, mid)` was already seen when it sent)

### Stage 6 — Edge cases

- [ ] Disconnect and reconnect BLE — heartbeat resumes within 5 s of reconnect
- [ ] Send 10 rapid messages — no duplicate processing (dedup cache works)
- [ ] Move boards far apart — RSSI changes; links change colour on topology (green → orange → red)
- [ ] Turn off ESP32 — `N2` fades on topology canvas after ~60 s inactivity

### Stage 7 — Unicast and ESP32 serial

- [ ] In Mesh tab, click node `N2` on the topology canvas — the destination dropdown switches to `→ N2`
- [ ] Send a unicast message to N2 — nRF serial shows `TX src=1 dst=2 mid=X ttl=5 '<text>'`
- [ ] ESP32 serial shows `RX src=1 dst=2 … '<text>'` and does NOT send a PONG (payload is not PARROT)
- [ ] nRF does NOT get a `MESH_RX` notification for the unicast (it was addressed to N2, not N1)
- [ ] Connect Chrome to ESP32 serial port (**ESP32 Serial → Connect Serial** in Mesh sidebar)
- [ ] Type a message in the serial input and click **TX** — ESP32 prints `Serial TX: <text>` and transmits it
- [ ] nRF receives the ESP32-originated message — dashboard Mesh log shows it as `MESH_RX` from `N2`
