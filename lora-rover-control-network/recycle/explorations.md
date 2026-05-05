# Adaptive-SF LoRa Rover Project Exploration Notes

## 1. What Was Built

This project now contains an end-to-end Python implementation of the planned architecture from overview.md, including:

1. Packet framing and typed payload codec with CRC checks.
2. SX1262-oriented radio abstraction with pluggable backends.
3. Neighbor table with fixed capacity, smoothing, and sliding windows.
4. Topology manager with weighted parent scoring and hysteresis.
5. Link-local adaptive spreading factor controller.
6. Dual route scoring modes: speed and throughput.
7. Forwarding pipeline with TTL, duplicate suppression, ACK retries, and queueing.
8. Rover command handling with watchdog safety behavior.
9. Telemetry snapshot, compact binary payload, and human-readable debug formatting.
10. Simulation harness for 3 to 5 nodes with decision logs.

Current automated validation status: 43 unit tests pass.

## 2. Engineering Decisions and Why They Matter

### 2.1 Layered Architecture

Decision:
Keep clear module boundaries among radio, protocol, networking, application, drivers, and utilities.

Why:
It lets the same firmware logic run on multiple node roles and board types while isolating hardware-specific risk.

### 2.2 Compact Binary Packet Design

Decision:
Use a small binary header with typed packet classes and CRC-16/CCITT-FALSE validation.

Why:
LoRa airtime is expensive, especially at higher SF. Compact payloads reduce latency and collision probability.

### 2.3 Fixed-Capacity Data Structures

Decision:
Neighbor and packet handling structures are bounded, with capped queues and duplicate windows.

Why:
This improves determinism on embedded targets and prevents silent memory growth in long-running nodes.

### 2.4 Parent Selection With Hysteresis

Decision:
Route selection uses weighted quality scoring plus margin-based switching and dwell-time controls.

Why:
Raw best-score switching is unstable in noisy links. Hysteresis avoids route flapping.

### 2.5 Link-Local Adaptive SF

Decision:
Each link adapts SF independently using fast-up and slow-down windows, cooldown, and optional probes.

Why:
Network-wide SF forces all links to worst-case behavior. Link-local control preserves performance where links are strong.

### 2.6 Forwarding Reliability Controls

Decision:
Use TTL decrement, duplicate suppression, ACK tracking, timeout retries, and bounded backoff.

Why:
These mechanisms are the minimum needed to avoid loops and packet storms while preserving delivery reliability.

### 2.7 Rover Safety First

Decision:
Rover executes only validated DATA commands, filters stale/duplicate sequence IDs, clamps motor values, and stops on watchdog timeout.

Why:
Control safety is more important than throughput. The rover should fail safe when communication quality degrades.

## 3. How Information Is Exchanged

Implementation note:

The exact control-cycle order is now implemented in `net/control_cycle.py` using `LinkRouteController.run_cycle(...)`:

1. Discover neighbors.
2. Estimate likely usable SF per link.
3. Convert predicted SF into route-cost influence.
4. Choose route.
5. Fine-tune SF on selected links.

## 3.1 Wire-Level Flow

Each transmitted frame carries:

1. Header fields: source, destination, previous hop, next hop, sequence, packet type, TTL, flags, SF, payload length.
2. Typed payload by packet class.
3. CRC over header plus payload.

Receiver flow:

1. Decode frame.
2. Validate CRC.
3. Validate payload schema for packet type.
4. Apply duplicate checks and TTL rules.
5. Consume locally or forward.

## 3.2 Packet Classes in Use

Implemented packet classes:

1. HELLO
2. BEACON
3. METRIC
4. DATA
5. ACK
6. SF_HINT
7. JOIN
8. REJOIN

DATA is used for command payloads and generic application bytes.

## 3.3 ACK and Retry Behavior

1. Local delivery can schedule ACK in a short reserved ACK gap.
2. Outbound packets marked as ACK-required are tracked with deadlines.
3. Expired ACK entries are retried up to a configured maximum.
4. Duplicate packets are suppressed through a recent sequence cache.

## 3.4 Bidirectional Controller and Rover Communication

Yes, two-sided communication is supported by design.

Controller to rover direction:

1. Controller sends DATA commands.
2. Rover validates and executes.
3. Rover sends ACK.

Rover to controller direction:

1. Rover can transmit telemetry DATA or telemetry payload packets.
2. Controller consumes, logs, and can ACK depending on policy.

This is fully aligned with the architecture. In the current codebase, rover-side logic is implemented and tested; controller-specific application behavior is still a thin stub and can be expanded next.

## 3.5 Can Two Controllers Communicate?

Short answer: yes, technically possible.

Long answer:

1. At protocol level, any node can send to any destination ID, including another controller.
2. At system-design level, two active controllers commanding one rover creates arbitration risk.

Recommended policy:

1. Single active control authority at a time.
2. Optional backup controller in standby mode.
3. If dual-controller mode is required, implement leader election or explicit command token ownership before issuing rover commands.

## 4. Current Implementation Reality

Implemented strongly:

1. Protocol, routing metrics, adaptive SF, forwarding, rover safety, telemetry encoding, simulation harness.

Implemented in this phase:

1. Controller app now supports command queueing, ACK completion handling, and inbound DATA consumption.
2. Relay app now performs decode + duplicate suppression + forwarding + local consume logging.
3. SX1262 MicroPython backend now includes SPI/pin setup, driver probing, config application, and operational send/receive hooks with graceful fallback.
4. OTA orchestration script is available at `tools/ota_orchestrator.py` for dry-run and optional execute mode.

Quick OTA examples:

1. Two-node dry run:

python tools/ota_orchestrator.py --scenario two-node --ports COM5,COM8

2. One-relay dry run:

python tools/ota_orchestrator.py --scenario one-relay --ports COM5,COM8,COM9

3. Execute commands:

python tools/ota_orchestrator.py --scenario two-node --ports COM5,COM8 --execute

## 5. Precise Test Steps

## 5.1 Baseline: Software-Only Regression

Use this first before any hardware test.

Windows PowerShell:

1. Open terminal at project root.
2. Run unit tests:

python -m unittest tests.test_sim_harness tests.test_telemetry tests.test_rover_app tests.test_forwarder tests.test_protocol_packets tests.test_radio_iface tests.test_neighbor_table tests.test_topology_manager tests.test_sf_controller tests.test_route_metric

3. Run simulation harness:

python tools/sim_harness.py

Expected:

1. All tests pass.
2. Harness prints logs for speed mode, throughput mode, SF decisions, duplicate suppression, and failover rejoin.

## 5.2 Two-Device Test With Current Hardware Only

Hardware you have now:

1. ESP32-S3 + SX1262
2. nRF52840 + SX1262

Goal:
Validate link and role behavior without a physical rover.

Procedure:

1. Configure one board as controller role and one board as rover role in runtime settings.
2. Use same frequency plan and LoRa PHY defaults on both boards.
3. Treat the rover role board as a virtual rover (no motor driver required).
4. Send command DATA frames from controller-side tooling or temporary test hook.
5. Verify on rover side:
   - sequence filtering works
   - invalid destination is ignored
   - watchdog behavior triggers safe stop state when commands stop
6. Verify ACK and retry behavior by intentionally dropping selected packets in test hooks.
7. Capture serial logs from both sides and compare sequence numbers and ACK timing.

Pass criteria:

1. Command ACK cycle is stable.
2. Duplicate commands are ignored.
3. Watchdog enters safe stop when command stream is interrupted.

## 5.3 Three to Four Devices: Add 1 to 2 Relays

Goal:
Validate forwarding, parent reselection, and mode-based path preference.

Topology examples:

1. Controller -> Relay A -> Rover
2. Controller -> Relay A or Relay B -> Rover

Procedure:

1. Place one relay in stronger line-of-sight path and another in weaker path.
2. Start in speed mode.
3. Inject periodic DATA and METRIC traffic.
4. Confirm parent score picks lower delay path.
5. Switch to throughput mode.
6. Confirm preference can shift toward more stable goodput path.
7. Force one relay outage and confirm rejoin and failover behavior.

Pass criteria:

1. Parent switches are hysteresis-stable.
2. Failover occurs without packet storms.
3. Duplicate suppression prevents looping artifacts.

## 5.4 With Rover Hardware Available

Goal:
Validate closed-loop motion safety and telemetry under real actuation load.

Procedure:

1. Mount rover node with motor driver connected.
2. Keep low speed cap at first.
3. Validate STOP command first.
4. Validate FORWARD, BACKWARD, TURN_LEFT, TURN_RIGHT at low speed.
5. Validate SET_SPEED clamping at and above limits.
6. Interrupt command stream and verify watchdog stop timing.
7. Run around-corner and obstructed tests with and without relay.

Pass criteria:

1. Rover never drives on malformed or stale commands.
2. Watchdog stop is consistent and repeatable.
3. Telemetry remains coherent while moving.

## 5.5 Drone Relay Test

Goal:
Measure benefit of elevated relay and characterize stability impact.

Procedure:

1. First emulate with high fixed point before flight.
2. Compare direct link, ground relay, and elevated relay at same locations.
3. In flight, keep hover mostly stationary initially.
4. Record route changes, SF changes, retries, and command latency.
5. Only then test slow movement trajectories.

Safety and control notes:

1. Drone relay should forward only; it should not own rover control decisions.
2. Keep command packet size small and ACK policy strict during drone runs.

Pass criteria:

1. Elevated relay improves reliability or latency in obstructed scenarios.
2. Mobility does not cause uncontrolled parent/SF oscillation.

## 6. Suggested Next Engineering Tasks

1. Implement controller app command publisher and telemetry consumer in app/controller.py.
2. Implement relay app coordination behavior in app/relay.py.
3. Add hardware runner scripts for board-specific deployment and serial log capture.
4. Add experiment data exporter for CSV logging of route and SF decisions.
5. Add controlled multi-controller arbitration policy if dual-controller control is required.

## 7. Key Project Files

Core logic files:

1. protocol/packets.py
2. protocol/crc.py
3. net/neighbor_table.py
4. net/topology.py
5. net/sf_controller.py
6. net/route_metric.py
7. net/forwarder.py
8. app/rover.py
9. app/telemetry.py
10. tools/sim_harness.py

Primary tests:

1. tests/test_protocol_packets.py
2. tests/test_radio_iface.py
3. tests/test_neighbor_table.py
4. tests/test_topology_manager.py
5. tests/test_sf_controller.py
6. tests/test_route_metric.py
7. tests/test_forwarder.py
8. tests/test_rover_app.py
9. tests/test_telemetry.py
10. tests/test_sim_harness.py
