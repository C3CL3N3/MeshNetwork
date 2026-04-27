# LoRa Mesh Network

**COMP 4531 — IoT and Smart Sensing | HKUST**

A flooding LoRa mesh network for Seeed XIAO boards as the final project for COMP 4531. Multiple nodes relay packets autonomously using TTL-based deduplication. A Web Bluetooth dashboard visualises the live mesh topology, shows per-link RSSI, and lets you broadcast messages across the network.

---

## Hardware

| Component | Role |
|---|---|
| Seeed XIAO nRF52840 Sense + Wio-SX1262 | Gateway node — relays mesh data to browser over BLE |
| Seeed XIAO ESP32-S3 + Wio-SX1262 | Pure LoRa relay node — no BLE required |
| SX1262 sub-GHz LoRa module | Radio link (900 MHz, SF7, BW 125 kHz) |

## Architecture

```
[ Browser Dashboard ]
        ↕  Web BLE
[ nRF52840 Node ]  ←——LoRa——→  [ ESP32-S3 Node ]  ←——LoRa——→  [ nRF52840 Node ]
      Node A                         Node B                         Node C
```

**Mesh Protocol — flooding with TTL deduplication:**

1. A node originates a packet `M:<src>:<msg_id>:<ttl>:<payload>`
2. Every node that receives an unseen `(src, msg_id)` pair:
   - Logs it / notifies the dashboard (if BLE-connected)
   - Decrements TTL and re-broadcasts after a per-node stagger (0–200 ms)
3. Duplicate `(src, msg_id)` pairs are silently dropped (rolling 30-entry cache)
4. Packets with TTL = 0 are not relayed further

Default TTL is 5, giving up to 5 relay hops. All nodes must share the same SF, BW, and frequency band.

## Radio Parameters

| Parameter | Value |
|---|---|
| Frequency | 900 + (GROUP\_ID − 1) MHz |
| Bandwidth | 125 kHz |
| Spreading Factor | SF 7 |
| Coding Rate | 4/5 |
| Max Hops (TTL) | 5 |

## Repository Structure

```
├── code_nrf.py              # CircuitPython firmware — nRF52840 mesh + BLE gateway
├── code_esp32.py            # CircuitPython firmware — ESP32-S3 LoRa relay node
└── COMP4531_Dash-main/
    ├── index.html           # Web dashboard
    ├── script.js            # BLE, LoRa, and mesh logic
    └── style.css            # Styling
```

## Setup

### Firmware

1. Flash CircuitPython on both boards (XIAO nRF52840 Sense and XIAO ESP32-S3).
2. Install the required libraries on each board's `lib/` folder:
   - `adafruit_ble` (nRF only)
   - `adafruit_ble.advertising`, `adafruit_ble.services`, `adafruit_ble.characteristics`
   - `sx1262` (SX1262 CircuitPython driver)
3. Set `GROUP_ID` at the top of each file to a **unique integer (1–30)** per board.
4. Copy `code_nrf.py` → `code.py` on the nRF board, `code_esp32.py` → `code.py` on the ESP32.

> All nodes must use the same `SF`, `BW`, and the same base frequency formula.

### Dashboard

The dashboard runs entirely in the browser — no server needed.

1. Open `COMP4531_Dash-main/index.html` in a Chromium-based browser (Chrome, Edge).  
   *(Web Bluetooth requires a secure context; use `localhost` or `https` if serving remotely.)*
2. Go to **Connect**, enter your Group ID, and click **Connect** to pair over BLE with your nRF node.
3. Switch to the **Mesh** tab to see the live topology.
4. Switch to the **LoRa** tab to chat and plot RSSI vs distance (send `"1m"`, `"5 meters"`, etc.).

## Dashboard

> The dashboard was adapted from the original lab dashboard provided by the **COMP 4531 TAs (HKUST)**. The IMU visualisation, audio recorder, Doppler analyser, and Flappy Bird mini-game tabs were removed. A **Mesh** tab was added with:
> - Force-directed topology canvas (dark theme)
> - RSSI-coloured links (green > −70 dBm · orange > −90 dBm · red below)
> - Animated message particles along links
> - Live node list with signal strength and last-seen age

## License

MIT
