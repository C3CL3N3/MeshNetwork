# Adaptive-SF LoRa Lab Checklist

Use this as an execution checklist during experiments. Fill it live while testing.

---

## 0. Session Metadata

- Date:
- Location:
- Team members:
- Weather (outdoor tests):
- Firmware commit hash:
- Controller node ID:
- Rover node ID (or virtual rover node):
- Relay node IDs:
- Drone relay node ID:

---

## 1. Pre-Flight Software Validation

### 1.1 Unit Tests

- [ ] Run full test suite.
- [ ] Confirm all tests pass.
- [ ] Save output log to test artifact folder.

Command:

python -m unittest tests.test_sim_harness tests.test_telemetry tests.test_rover_app tests.test_forwarder tests.test_protocol_packets tests.test_radio_iface tests.test_neighbor_table tests.test_topology_manager tests.test_sf_controller tests.test_route_metric

Result notes:

-

### 1.2 Simulation Harness

- [ ] Run simulation harness.
- [ ] Confirm logs include: speed_mode, throughput_mode, sf_actions, duplicate_check, failover.

Command:

python tools/sim_harness.py

Result notes:

-

---

## 2. Hardware Bring-Up Checklist (Any Physical Test)

- [ ] Correct board profile selected on each node.
- [ ] Matching frequency/bandwidth/coding-rate/SF defaults.
- [ ] Node IDs unique.
- [ ] Role set correctly on each node.
- [ ] Serial logging enabled and readable.
- [ ] Power source stable.
- [ ] Antenna connected correctly.

Per-node table:

| Node | Board | Role | Node ID | Power | Antenna | Serial OK |
|---|---|---|---|---|---|---|
| A |  |  |  |  |  |  |
| B |  |  |  |  |  |  |
| C |  |  |  |  |  |  |
| D |  |  |  |  |  |  |
| E |  |  |  |  |  |  |

---

## 3. Two-Device Test (Current Available Setup)

Target setup now:

1. ESP32-S3 + SX1262
2. nRF52840 + SX1262

Suggested role assignment:

1. Node A: controller
2. Node B: rover (virtual rover, no physical motors required)

### 3.1 Link and Command Path

- [ ] Controller sends DATA command sequence.
- [ ] Rover-side node receives packets addressed to its node ID.
- [ ] ACK responses are observed.
- [ ] Duplicate packets are ignored.

Measurements:

- Mean command RTT:
- P95 command RTT:
- Packet success ratio:
- ACK retry count:

### 3.2 Safety Behavior (Virtual Rover Validation)

- [ ] STOP command is accepted.
- [ ] FORWARD/BACKWARD/TURN commands parse correctly.
- [ ] SET_SPEED clamping works.
- [ ] Stale/duplicate sequence is rejected.
- [ ] Watchdog stop triggers when command stream pauses.

Observations:

-

Pass criteria:

- [ ] Two-way command/ACK works repeatedly.
- [ ] Safety checks hold under packet loss and duplicate injection.

---

## 4. Three-Node Test (1 Relay)

Suggested roles:

1. Node A: controller
2. Node B: relay
3. Node C: rover or virtual rover

### 4.1 Forwarding and TTL

- [ ] Relay forwards controller traffic when direct path is degraded.
- [ ] TTL decrements correctly.
- [ ] Duplicate suppression active at relay.

### 4.2 Parent Selection and Hysteresis

- [ ] Parent selected by score (not random).
- [ ] Parent does not flap under small metric changes.
- [ ] Parent switches when alternative improves beyond hysteresis margin.

### 4.3 Failover

- [ ] Induce relay or link outage.
- [ ] Observe rejoin_required trigger.
- [ ] Confirm recovery to stable parent.

Measurements:

- Parent switch count:
- Time to recover from outage:
- Packet success during failover:

Pass criteria:

- [ ] Forwarding stable.
- [ ] No loops/storms.
- [ ] Failover recovers without unsafe behavior.

---

## 5. Four-to-Five Node Test (1-2 Relays)

Goal: compare speed mode and throughput mode with different link qualities.

### 5.1 Speed Mode

- [ ] Set mode to speed.
- [ ] Verify lower-latency path preferred.
- [ ] Confirm command RTT improvement vs throughput mode baseline.

### 5.2 Throughput Mode

- [ ] Set mode to throughput.
- [ ] Verify more stable-goodput path preferred.
- [ ] Confirm reduced loss/retries on telemetry bursts.

Measurements table:

| Mode | Avg RTT | P95 RTT | Delivery % | Retries | Selected Parent Path |
|---|---:|---:|---:|---:|---|
| speed |  |  |  |  |  |
| throughput |  |  |  |  |  |

Pass criteria:

- [ ] Mode switch changes scoring behavior as expected.
- [ ] Results match route metric intent.

---

## 6. Adaptive SF Validation

Run this in both stable and degraded channel conditions.

### 6.1 Fast Upward Shift (Reliability Protection)

- [ ] Induce degradation (lower SNR / higher retries).
- [ ] Observe SF suggestion/action increase within configured n_up window.
- [ ] Confirm packet reliability recovers.

### 6.2 Slow Downward Shift (Efficiency Recovery)

- [ ] Restore stable conditions.
- [ ] Observe delayed SF decrease after n_down stable windows.
- [ ] Confirm no rapid oscillation.

### 6.3 Probe Behavior

- [ ] Confirm periodic lower-SF probe appears on stable link.
- [ ] Confirm probes remain low-rate.

Record:

- SF change events (time, from, to, reason):
- Probe count:
- Oscillation observed? (yes/no):

Pass criteria:

- [ ] Fast-up and slow-down behavior observed.
- [ ] Cooldown respected.
- [ ] Oscillation controlled.

---

## 7. Rover Hardware Test (When Rover Is Available)

### 7.1 Safety-First Bring-Up

- [ ] Wheels lifted or chassis constrained initially.
- [ ] STOP command verified first.
- [ ] Low speed cap enabled first.

### 7.2 Motion Commands

- [ ] FORWARD
- [ ] BACKWARD
- [ ] TURN_LEFT
- [ ] TURN_RIGHT
- [ ] SET_SPEED
- [ ] HEARTBEAT handling

### 7.3 Fault Injection

- [ ] Stop command stream to trigger watchdog stop.
- [ ] Send duplicate sequence command and verify reject.
- [ ] Send malformed command and verify reject.

Pass criteria:

- [ ] Rover never executes stale/invalid commands.
- [ ] Rover stops safely on timeout.

---

## 8. Drone Relay Test (When Available)

### 8.1 Ground Emulation First

- [ ] Place relay at elevated fixed point.
- [ ] Compare against direct and ground-relay paths.

### 8.2 Hover Relay

- [ ] Keep drone mostly stationary first.
- [ ] Verify path selection and SF adaptation remain stable.

### 8.3 Controlled Motion

- [ ] Introduce slow drone movement.
- [ ] Track route changes, retries, and command latency.

Safety notes:

- [ ] Drone is forwarding-only; no rover control logic on drone.
- [ ] Flight and local regulations observed.

Pass criteria:

- [ ] Elevated relay benefit is measurable in obstructed paths.
- [ ] No unstable oscillation in routing/SF decisions.

---

## 9. Multi-Controller Exploration Checklist

If testing two controllers:

- [ ] Define which controller is active authority.
- [ ] Define standby controller behavior.
- [ ] Prevent simultaneous conflicting command streams.

Recommended engineering policy:

- [ ] Add explicit command ownership token.
- [ ] Add lease timeout and takeover rules.
- [ ] Log authority changes.

Pass criteria:

- [ ] No conflicting command actuation at rover.
- [ ] Deterministic controller handover behavior.

---

## 10. Data Capture Template

For each run:

- Test name:
- Topology:
- Mode (speed/throughput):
- SF policy state:
- Distance/obstructions:
- Avg RTT:
- Delivery ratio:
- Retry ratio:
- Parent switches:
- SF switches:
- Watchdog events:
- Notes:

---

## 11. Go/No-Go Gate

Release candidate gate:

- [ ] All software tests pass.
- [ ] Two-device bidirectional command/ACK is stable.
- [ ] Relay failover and rejoin validated.
- [ ] Adaptive SF behavior validated.
- [ ] Rover watchdog safety validated (or simulated if rover unavailable).

Decision:

- [ ] GO
- [ ] NO-GO

Reason:

-
