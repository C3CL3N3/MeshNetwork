# LoRa Rover Control Network — Agent Onboarding

Status: active
Last updated: 2026-05-05
Scope: project orientation for AI agents

## What This Project Is

A LoRa mesh control network using Semtech SX1262 radios (ESP32-S3 and nRF52840 boards). Fixed-SF7 H/R/D protocol with distance-vector routing, controller-relay-endpoint topology, BLE + serial dashboard, and DTN store-carry-forward queue.

The repo lives at `academic/study-material/semester-04/iot/06-code/lora-rover-control-network/`. The companion friend repo is `MeshNetwork/` (branch `cleanup-sf7`).

## Deployed Files (What Actually Runs)

Three files are flashed to CIRCUITPY:

| File | Role |
|------|------|
| `toDevice/sx1262.py` | Custom SX1262 CircuitPython driver (CAD, LBT, async RX, RSSI/SNR) |
| `toDevice/mesh_core.py` | Single-file runtime — hardware, protocol, network, endpoints, actuators, BLE gateway, topology tracker (~1400 lines) |
| `toDevice/code.py` | Board entrypoint — imports mesh_core, builds hardware, runs main loop |

The dashboard flashes these with node-specific config patched in (GROUP_ID, NODE_ID, ROLE, BOARD_PROFILE, etc.).

The files under `toDevice/software/` and `toDevice/hardware/` are the modular source — `mesh_core.py` is the inlined deployment version. Keep them in sync.

## Architecture

```
Controller (C) ─── BLE ─── Dashboard (browser)
     │
     ├── Hello broadcast (H:src:role:sf)
     ├── Route advertisement (R:orig:fwd:mid:hops[:path_rssi:path_snr])
     ├── Data packet (D:src:dst:next_hop:mid:ttl:payload)
     │   ├── T: topology report (neighbor list with RSSI+SNR)
     │   ├── O: orientation (full route table to new neighbor)
     │   ├── WELCOME: role announcement
     │   ├── SF: SF change command (currently frozen)
     │   └── SERVO:, CAPS?, PING, CMD:, ENDPOINT:DEBUG etc.
     │
     ├── Route table (distance-vector, 90s expiry, fastest/reliable policies)
     ├── Neighbor table (120s expiry, RSSI+SNR+role)
     ├── DTN queue (30s TTL, 3s retry, control payloads excluded)
     ├── Topology tracker (aggregates T: reports into full network graph)
     └── Traffic mode (BOOT→ACTIVE→NORMAL→QUIET; controls packet cadence only)
```

Node roles: **C** (controller, BLE gateway), **R** (relay, forward-only), **E** (endpoint/gadget, servo actuator).

## What Was Done (All Fixes Applied)

### SF Management (now FROZEN at SF7)
- SF was inconsistent because the controller broadcast SF commands but never applied them locally (`code.py` only called `send_data`, not `_apply_sf_change`).
- Self-broadcast dedup prevented the controller from receiving its own SF command.
- 30s cooldown silently dropped explicit SF changes with no retry.
- **Fix**: Added `mesh.set_sf()` public method that applies locally + broadcasts. Added `force` param to skip cooldown.
- **Current state**: SF frozen at 7. `SF_AUTO_ENABLED = False`, `_cfg['sf_mode'] = "7"`, and `SF_SCAN_ENABLED = False`. `set_sf()` is a no-op. Boot/reconnect SF sweeps are skipped. Over-the-air `SF:` commands are dropped and not forwarded. Adaptive thresholds/code are kept only as future work and are inactive.

### SX1262 Radio Recovery
- After TX timeout, `send()` threw before cleanup — radio stuck in TX mode with BUSY high. All subsequent TX failed.
- **Fix**: Restructured `send()` to always attempt cleanup. Added `_force_standby()` (graceful standby → hardware reset + full `begin()` re-init). Increased `_wait_busy` timeout to 200ms. RadioAdapter adds 10ms settling delay after errors.
- **Current state**: `send()` now programs a finite SX1262 TX timeout instead of no-timeout TX, and explicitly forces standby before raising `SX1262 TX timeout`. Management packet logs now distinguish successful `TX_H` / `TX R` from `TX_FAIL ...`, so serial logs no longer imply a hello/route was transmitted after `radio tx err`.

### Node Reconnection
- Earlier logic tried to recover isolated nodes by scanning SFs, which is incompatible with the current fixed-SF7 deployment.
- That left a bug where `scan_for_network()` still swept SF7→SF12 at boot even though `_cfg['sf_mode'] = "7"`.
- **Fix**: Fixed-SF7 mode now forces the radio back to SF7 and skips boot scan, reconnect scan, and SF command forwarding. Isolated nodes can still move to ACTIVE mode for faster hello/route cadence, but they do not leave SF7.

### SNR Display
- Topology protocol (`T:` packets) only encoded RSSI, not SNR. Extended to 4-field format: `nid,rssi,snr`.
- **Critical bug**: `meshD3Update()` route link builder omitted the `snr` field entirely — only physical/topology links carried SNR. Direct neighbor links never showed SNR labels.
- Route link updates (`_serialMeshRoute`) unconditionally overwrote link data with `snr: null`, wiping SNR set by neighbor processing.
- Serial RX D log line didn't include SNR.
- **Fix**: Route link builder now includes `snr` with node SNR fallback. Route updates preserve existing SNR. Serial RX D includes `snr=X.X`. Topology protocol extended with SNR.
- **Hop count**: Serial regex only matched `[NEW]` route lines, not `[known]` refreshes. Hop counts never updated after first discovery. Fixed to match both.

### Stale / Gone Nodes
- Topology handlers only created new nodes — never updated `lastSeen` on existing ones. Nodes visible only through topology reports went grey after 30s.
- **Fix**: Topology handlers separate "mentioned in topology" from "live presence". Active links render solid. When an authoritative topology snapshot omits a previously known edge, that edge immediately becomes dashed and fades out over 30s while still holding layout position. Nodes with no live links turn grey; after all visible links expire they are parked outside the rings and fade out until removal at 2.5 minutes.

### Dashboard
- Replaced CSS `resize` property with proper drag handles for sidebar and log panel (saves to localStorage).
- D3 data key now immune to source/target type changes (numbers vs node objects after simulation).
- SF display updated from serial SF_CHG/SF:locked/SF:mode=auto lines.
- Variable name bugs fixed (`nid`→`nodeId`, nonexistent `meshNetSf`→`sfSelect`).

### Relay Chain Reliability
- Topology reports used probabilistic flooding (~85% per hop) — end-to-end delivery degraded exponentially with chain length.
- **Fix**: `T:` payloads always forward (bypass `_relay_probability()`). `SF:` commands are dropped while fixed-SF7 mode is active.
- Control forwarding can fall back to fresh topology if a route table entry expired but the network still reports a 30s-fresh path. Forwarding now logs `TOPO_ROUTE`, `FWD D`, `FWD_FAIL D`, or `DROP relay no route ... control`.
- Route ads now carry optional path bottleneck RSSI/SNR while still accepting legacy 4-field ads. `reliable` mode (default) scores bottleneck RSSI/SNR and can choose a stronger multi-hop chain over a weak short route; `fastest` mode keeps hop-count-first behavior.
- The mesh page has a route selector. `ROUTE_MODE:reliable` / `ROUTE_MODE:fastest` is applied locally on the controller and broadcast to the rest of the mesh.
- Topology reports are more conservative: initial/change reports remain urgent, repeats are suppressed for 20s, and boot/active fallback refreshes are 300s instead of 120s.

## What Still Needs Doing

### High Priority
1. **Hardware deployment testing**: Flash all boards with current `mesh_core.py`, verify connectivity at SF7, check SNR labels on dashboard, test multi-hop chains.
2. **Re-enable adaptive SF** (after SF7 is validated): Treat this as a deliberate future task. It should reintroduce `SF_AUTO_ENABLED = True`, boot/reconnect SF scans, `SF:` packet forwarding, and `_cfg['sf_mode'] = "auto"` together, with hardware tests. Do not partially enable any of these while validating fixed SF7.
3. **TX reliability**: If `SX1262 busy timeout` or `TX timeout` errors reappear, investigate hardware (RF switch, DIO1 pin, antenna). The software recovery is in place but won't fix broken hardware.

### Medium Priority
4. **RSSI history / link quality graphing**: No per-link RSSI/SNR history is tracked. Adding a rolling window would help debug RF issues.
5. **Packet delivery ratio tracking**: No end-to-end ACK mechanism. Control payloads have no delivery guarantee (DTN disabled for control). Add sequence-number-based PDR tracking.
6. **Orientation packet scope**: Orientation sends the FULL route table on every new neighbor discovery. For large networks, this could be large. Consider limiting to N most recent/best routes.

### Low Priority
7. **BLE reconnection backoff**: BLE auto-reconnect backs off 1s→2s→5s→10s→15s (repeats). No jitter. Consider exponential backoff with jitter.
8. **Dashboard flash from serial**: Currently flash requires File System Access API (Chrome). Serial-only flash would help field deployment.
9. **Unit test coverage**: Only `test_software_mesh.py` exists. No tests for SX1262 driver, adaptive SF, or topology tracker.

## Important Considerations

### SF is Frozen
Do NOT re-enable adaptive SF until base SF7 connectivity is validated on hardware. The adaptive thresholds are set to Semtech demodulation floors and require 2 consecutive bad readings — this should be conservative enough, but it hasn't been tested.

### Dual Codebase
`mesh_core.py` is the DEPLOYED version (flat, inlined). `toDevice/software/` and `toDevice/hardware/` are the MODULAR version (import-based). Changes must be made to both, or to `mesh_core.py` and then synced back to the modular files.

### CircuitPython Limitations
- No `asyncio` — everything is synchronous polling.
- Limited RAM — `mesh_core.py` is already ~1400 lines. Avoid large data structures.
- `time.monotonic()` is seconds (float), not milliseconds.
- `sys.stdin.read()` for serial input, `print()` for serial output.

### Radio Quirks
- SX1262 BUSY pin is active-high. Driver polls it before each SPI command.
- `recv_start()` must be called after every TX and after every successful RX to re-enter continuous RX mode.
- CAD (Channel Activity Detection) takes ~2 symbol times: SF7/125kHz ≈ 0.7ms, SF12 ≈ 66ms.
- LBT (Listen-Before-Talk) uses CAD with exponential backoff (20ms base, 40ms jitter, max 5 tries).

### Network Behavior
- Mode intervals are hello/route/topology fallback: BOOT 5/5/300s, ACTIVE 10/10/300s, NORMAL 10/30/300s, QUIET 30/60/600s.
- Periodic hello/route/topology packets are staggered with a short management TX gap; `T:` is not sent as the third packet in a same-tick burst.
- Discovery/change-triggered topology reports are marked urgent and take priority once their scheduled delay expires.
- A node in QUIET switches back to ACTIVE and sends WELCOME, orientation, then a scheduled near-term topology report when it hears a controller hello. This handles controller restarts without waiting for the next quiet topology report.
- Local `T:` topology transmissions bypass CAD/LBT and print `TX T seq=... nbrs=...` or `TX_FAIL T ...`; this avoids silent suppression when CAD falsely sees the SF7 channel as busy.
- Neighbor expiry: 120s. Route expiry: 90s. Topology expiry: 30s.
- DTN: 30s TTL, 3s retry, max 16 items. Control payloads excluded from DTN.
- Broadcast forwarding: probabilistic (40%–97% based on RSSI). `T:` topology reports always forward. `SF:` commands are dropped while fixed-SF7 mode is active.
- Route TTL: 5 hops max.
- Routing mode defaults to `reliable`. `fastest` prioritizes fewer hops; `reliable` uses advertised path bottleneck RSSI/SNR plus hop penalty. Topology fallback also follows the selected policy.

### Dashboard
- Open `dashboard/index.html` in Chrome/Edge (needs Web Bluetooth and/or Web Serial).
- Hard-refresh (Ctrl+Shift+R) after any JS/CSS changes.
- Flashing writes only the deployed flat files: `sx1262.py`, `mesh_core.py`, and `code.py`.
- nRF52840 supports roles `C` and `E`; ESP32-S3 supports roles `C`, `R`, and `E`. Both board types run the same role classes after board-specific hardware setup.
- Graph layout is intentionally damped: normal RSSI/topology refreshes update labels without reheating the force simulation. Dragging a non-controller node pins it where placed; double-click releases the manual pin. The controller remains fixed in the center.
- The graph uses one link visual model: solid = actively connected, dashed = missed/stale/disconnected. Dashed links fade for 30s while still holding topology layout; after they disappear, disconnected nodes park outside the rings, greyed/fading, and expire after 2.5 minutes.
- Link labels use a consistent midpoint position: dBm above the line midpoint, SNR below it.
- Nodes with no live solid links are grey. Nodes are removed after 2.5 minutes disconnected.
- Serial-connected: node ID auto-detected from `Node X role=Y` or `TX_H NX|Y|` lines.
- BLE-connected: uses nRF52840 as gateway. Group ID selects BLE UUID and frequency (900 + group_id - 1 MHz).
- Rover control simulation uses a fixed 700x560 world-coordinate grid centered at `(0,0)`, with `+X` east and `+Y` north. Compass bearings are `0=N`, `90=E`, `180=S`, `270=W`; the compass, waypoint planner, pointer hit-testing, and canvas rover use the same conversion helpers. Canvas waypoint handles are draggable with native pointer events; the rover is drawn as a small car/arrow body with an explicit north-facing local front.

## Verification Checklist

- [ ] Flash 2+ boards, verify all appear in dashboard node list
- [ ] SNR labels visible on ALL links (direct + inter-node) in D3 graph
- [ ] Send message to specific node — verify delivery via serial log
- [ ] Form a 3+ node chain, verify multi-hop routes appear with correct hop counts
- [ ] Move a node out of range, verify links turn dashed immediately on the first missing topology snapshot or after ~12s stale age, fade/disappear by 30s, node parks outside the rings, and node fades out by 2.5m
- [ ] Bring node back in range, verify it reconnects and re-enters graph within ~10s
- [ ] Manual SF=7 selected — verify no SF broadcasts and no `SCAN: CAD sweep SF7→12` / `RECONNECT: re-scanning SF7→12` lines in serial log
