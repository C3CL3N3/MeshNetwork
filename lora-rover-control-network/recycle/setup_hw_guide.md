# Hardware Setup and Test Guide (CircuitPython-First)

This guide is now tailored for CircuitPython deployment on your boards.

Target hardware:

1. ESP32-S3 + SX1262
2. nRF52840 + SX1262

---

## 1. PC Prerequisites (Windows PowerShell)

Install required tools:

1. Python 3.10+
2. pyserial (for monitoring)
3. esptool (only if your ESP32-S3 board requires BIN flashing)
4. adafruit-ampy (optional helper for file copy)

Commands:

pip install --upgrade pyserial esptool adafruit-ampy

Optional:

pip install -U pip

---

## 2. Configure Project for CircuitPython

In toDevice/device_code/config.py set:

1. RADIO_BACKEND = "circuitpython"
2. BOARD_PROFILE = "esp32s3_sx1262" on ESP32-S3 nodes
3. BOARD_PROFILE = "nrf52840_sx1262" on nRF52840 nodes

If both board types run at the same time, keep node-local copies of toDevice/device_code/config.py per board.

---

## 3. Install CircuitPython Firmware

## 3.1 nRF52840

1. Enter UF2 bootloader mode.
2. Copy the correct CircuitPython UF2 for your exact board.
3. After reboot, confirm CIRCUITPY drive appears.

## 3.2 ESP32-S3

Use your board's official CircuitPython install flow:

1. If UF2 is supported, copy UF2 and reboot.
2. If only BIN flashing is supported, use esptool with vendor-provided instructions.

After successful install, confirm CIRCUITPY drive appears.

---

## 4. Install SX1262 Libraries on CIRCUITPY

Copy required radio libraries to CIRCUITPY/lib:

1. adafruit_sx1262.mpy (or compatible sx1262.py module)
2. Any additional dependency modules required by your SX1262 driver package

Notes:

1. board, busio, and digitalio are provided by CircuitPython runtime.
2. If initialize fails, check startup line for last_error details.

---

## 5. Deploy Project Files to CIRCUITPY

Use the deployment-only tree in toDevice.

Copy both of these to CIRCUITPY root:

1. toDevice/code.py -> CIRCUITPY/code.py
2. toDevice/device_code/ -> CIRCUITPY/device_code/

Example PowerShell copy flow (replace drive letter):

Copy-Item -Recurse -Force .\toDevice\device_code H:\device_code
Copy-Item -Force .\toDevice\code.py H:\code.py

Template H:/code.py content:

import sys
sys.path.insert(0, "/device_code")
import runtime_config as r
import main

c = r.get_runtime_config()
c.parse_command("ROLE:controller")
c.parse_command("NODE:1")
c.parse_command("BOARD:esp32s3_sx1262")
main.main()

Set ROLE, NODE, and BOARD per device by editing the three parse_command lines in each board's code.py.

Controller BLE command bridge:

When role is controller, use BLE to send commands without editing files or rebooting.

The controller exposes a BLE command bridge using the same STATUS / TARGET / HEARTBEAT / SEND / SEND_LORA command pattern.

At startup, the controller initializes BLE and begins advertising right away; once connected, it stops advertising and reads commands from the BLE control characteristic.

Lab radio defaults:

1. Group ID defaults to 13.
2. Frequency is derived from the group ID in `toDevice/device_code/config.py`.
3. LoRa receive polling uses a longer timeout to match the lab-style listen loop.

Supported commands:

1. STATUS
2. TARGET:<node_id>
3. HEARTBEAT:ON or HEARTBEAT:OFF
4. SEND:<command and args> (example: SEND:FORWARD, SEND:SET_SPEED 120)
5. SEND_LORA:<raw payload text> (transmit immediately over LoRa)

---

## 6. Start and Verify Runtime

CircuitPython runs code.py automatically after reset.

Startup should print:

RADIO CHECK backend=... board=... initialized=... spi=... driver=... sf=... last_error=...

Use this line as first health check.

Expected for healthy setup:

1. backend=circuitpython
2. initialized=True
3. spi=True
4. driver=True
5. last_error=None

---

## 7. Monitor Packets and Decisions (Live)

Use the board logs and BLE client output to watch runtime behavior.

What to watch:

1. FWD events: queue, ack_wait, ack_retry, drop_duplicate, forward_queued
2. Controller RX DATA and ACK lines
3. Relay forwarding and duplicate suppression
4. SF update lines from controller or relay

---

## 8. Observe SF Optimization

## 8.1 Deterministic simulation

python tools/sim_harness.py

Expect:

1. stage-order logs
2. route selections
3. sf_actions and SF outcomes
4. duplicate suppression
5. failover and rejoin behavior

## 8.2 Physical trend test

1. Start with close, stable nodes.
2. Increase path loss with distance or obstruction.
3. Observe SF increases under reduced link quality.
4. Restore quality and confirm slower SF decreases.

---

## 9. Recommended Test Setups

## 9.1 Two-device setup

Nodes:

1. Controller: ESP32-S3 (Node 1)
2. Virtual rover: nRF52840 (Node 2)

Steps:

1. Install CircuitPython on both boards.
2. Deploy app files and code.py per node.
3. Set ROLE and NODE in each code.py.
4. Reset both boards.
5. Start serial monitor.
6. Verify ACK and watchdog behavior.

## 9.2 One-relay setup

Nodes:

1. Controller
2. Relay A
3. Rover or virtual rover

Steps:

1. Set relay ROLE and NODE in relay code.py.
2. Reset all nodes.
3. Place relay in beneficial position.
4. Observe forwarding, retries, and duplicate handling.
5. Run outage and recovery test.

## 9.3 Two-relay setup

1. Place relays on different quality paths.
2. Compare speed and throughput mode behavior.
3. Observe parent switching and hysteresis stability.

## 9.4 Rover and drone-relay setups

1. Verify STOP behavior before motion tests.
2. Validate low-speed movement commands first.
3. For drone relay, begin static then slow motion.
4. Record retries, latency, route switches, and SF changes.

---

## 10. Fast Troubleshooting (CircuitPython)

Issue: no serial output

1. Confirm correct COM port.
2. Confirm board rebooted into CircuitPython.
3. Check code.py exists at CIRCUITPY root.

Issue: RADIO CHECK shows initialized=False

1. Confirm toDevice/device_code/config.py has RADIO_BACKEND = "circuitpython".
2. Confirm SX1262 driver file exists in CIRCUITPY/lib.
3. Use last_error field to identify missing module, pin mapping, or constructor mismatch.

Issue: no radio traffic

1. Confirm all nodes share frequency, bandwidth, coding rate, and SF defaults.
2. Confirm board profile matches hardware on each node.
3. Confirm SX1262 wiring and board pin mapping in boards/*.py.

Issue: no SF adaptation visible

1. Validate policy in simulation first.
2. Create stronger link-quality change in physical setup.
3. Watch SF update logs on controller and relay.

---

## 11. Legacy Note: OTA Orchestrator

tools/ota_orchestrator.py currently uses mpremote and is MicroPython-oriented.

For CircuitPython, prefer direct CIRCUITPY file copy workflow in this guide.
