# Dashboard

This dashboard is adapted from the friend's `MeshNetwork cleanup-sf7` website.

## Run Locally

Run a local static server from the repo root:

```powershell
python -m http.server 8000
```

Then open:

```text
http://localhost:8000/dashboard/
```

Use Chrome or Edge because flashing requires the File System Access API.

## Launch And Flash

1. Open a terminal in the repo root:

```powershell
cd C:\AI\Agent-worklab\personal_workspace\academic\study-material\semester-04\iot\06-code\lora-rover-control-network
python -m http.server 8000
```

2. Open `http://localhost:8000/dashboard/`.
3. In the dashboard, set `group_id`.
4. Pick the `node_id`.
5. Pick the `board`.
6. Pick the `role` for that board.
7. Click `flash`.
8. When prompted, pick that board's `CIRCUITPY` drive.
9. Wait for the board to reboot.

If you unplug one board and plug in another, the browser may keep a stale remembered drive handle for that board type. The dashboard now probes the remembered handle and will ask you to re-select the `CIRCUITPY` drive if needed. You can also click the `✕` beside `nrf_drive` or `esp32_drive` to forget it manually.

Recommended first setup:

- nRF52840: `node_id = 1`, role `C`
- ESP32-S3: `node_id = 2`, role `E`

## MG90S Default

Current defaults are aligned for an MG90S-style PWM servo:

- `ENDPOINT_ACTUATOR = "pwm_servo"`
- `ENDPOINT_SERVO_PIN = "D7"`

If the servo does not move but the endpoint replies with `ACK:SERVO`, the network path is working and the remaining issue is actuator wiring or the wrong driver board mode.

## Flash Behavior

The flash buttons write the structured firmware package to the selected `CIRCUITPY` drive:

- `code.py`
- `sx1262.py`
- `mesh_core.py`

The dashboard patches `GROUP_ID`, `NODE_ID`, `BOARD_PROFILE`, `ROLE`, `ALLOW_EXTERNAL_COMMANDS`, `REPORT_TOPOLOGY`, and `CONTROLLER_ID` while writing `mesh_core.py`.

Supported roles:

- nRF52840: `C` controller, `E` endpoint
- ESP32-S3: `C` controller, `R` relay, `E` endpoint

Only controller firmware accepts BLE and serial application commands. Relay and endpoint firmware still sends mesh-management packets, but does not originate arbitrary user traffic.
The dashboard refuses to flash a non-controller with the same `node_id` as the remembered `controller_id`; duplicate node IDs break routing and topology.

If you connect the dashboard to a node over USB serial instead of BLE:

- the mesh send box now falls back to serial transport
- unicast uses `TO:<dst>:<payload>`
- selecting `self [N<id>]` sends a local command to that serial-connected node

The mesh graph is damped to avoid idle pulsation. Regular RSSI/topology refreshes should not kick the whole layout. Drag a non-controller node to pin it in place; double-click that node to release it back to the live layout. The controller stays fixed at the center.

The graph uses one link visual model: solid means actively connected, dashed means recently missed/stale/disconnected. A missed topology edge turns dashed immediately and fades for 30 seconds while still holding layout position. A node with no live solid links turns grey; after its visible links disappear it parks outside the rings and fades out until removal at 2.5 minutes. Link labels stay at the midpoint with dBm above and SNR below.

Endpoint firmware supports addressed commands such as `CAPS?`, `PING`, and `SERVO:<angle>`. The default MG90S PWM signal pin is configured in `toDevice/software/config.py` as `ENDPOINT_SERVO_PIN = "D7"`.

## First Test

After flashing:

1. Connect the dashboard to the nRF controller over BLE.
2. Wait until node `N2` appears in the mesh view.
3. Send:

```text
CAPS?
```

to endpoint node `2`.

4. Then send:

```text
SERVO:30
SERVO:120
```

to node `2`.

If `ACK:SERVO` comes back, firmware and routing are working.

## Serial Mesh Diagnostics

When a board is connected through the serial tab, the dashboard discovers the
local node passively from the firmware's own output. A healthy flashed node
should print lines like:

```text
=== mesh boot ===
mesh imports ok
lora ok  912.0 MHz  SF7
Node 2 role=E board=esp32_sx1262 freq=912.0MHz SF7
MESH_INFO:NODE_ID:2|SF:7|ROLE:E|BOARD:esp32_sx1262|GID:13|FREQ:912.0
TX_H N2|E|SF7
TX R mid=1
```

Useful local serial commands:

```text
INFO
NEIGHBORS
ROUTES
```

Do not send text while CircuitPython is still showing `Press any key to enter the
REPL`. Input during that boot window enters REPL and prevents `code.py` from
running. Wait until `Node ...`, `MESH_INFO...`, or `TX H ...` appears.

If `INFO` works but no `RX H` ever appears on either board, the firmware is running
but the LoRa link is not receiving. Check matching `group_id`, board profile,
node IDs, antennas, and SX1262 wiring.

## Endpoint Debug Mode

The endpoint supports a debug sender mode.

Over mesh, send to the endpoint node:

```text
ENDPOINT:DEBUG:ON
ENDPOINT:DEBUG:ON:1
ENDPOINT:DEBUG:STATUS
ENDPOINT:DEBUG:OFF
```

When enabled, the endpoint sends `P<time>` to the target node every 10 seconds.

Local CLI on the endpoint also supports:

```text
DEBUG:ON
DEBUG:ON:1
DEBUG:STATUS
DEBUG:OFF
```

When the dashboard is serial-connected directly to an endpoint, select `self [N<id>]` in the destination dropdown and use the debug buttons there.
