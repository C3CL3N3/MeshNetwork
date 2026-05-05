# LoRa Endpoint Control Network Architecture

## Current Direction

This repo uses a layered firmware structure:

- `toDevice/hardware/`: board-specific pins, SX1262 setup, RF switch control, BLE and serial helpers.
- `toDevice/software/protocol/`: fixed-SF7 H/R/D packet codec.
- `toDevice/software/network/`: neighbor discovery, route advertisements, route table management, deduplication, DTN for non-control data, and forwarding.
- `toDevice/software/endpoints/`: role-specific behavior for controller, relay, and generic endpoint nodes.
- `toDevice/software/gateway/`: BLE dashboard bridge for the controller node.
- `dashboard/`: browser UI copied from the friend's `cleanup-sf7` branch and adapted to flash this structured firmware tree.

The application model is controller-relay-endpoint, not a flat "every node is an app sender" mesh.

## Node Roles

- `controller`: the only role that accepts external BLE or serial commands. It originates endpoint and diagnostic traffic.
- `relay`: participates in hello, route advertisement, route learning, and packet forwarding only.
- `endpoint`: addressed gadget endpoint. Current optional capability is PWM servo control through `SERVO:<angle>`.
- `observer`: can receive/observe mesh state without acting as a control endpoint.

All nodes still send protocol-management packets such as `H` and `R`. That is required for routing. The restriction is at the application layer: non-controller nodes do not originate arbitrary user commands.

## Mesh Management

The network uses the fixed-SF7 protocol from the friend's branch:

- `H:<src>` announces a directly reachable neighbor.
- `R:<orig>:<fwd>:<mid>:<hops>` advertises routes.
- `D:<src>:<dst>:<next_hop>:<mid>:<ttl>:<payload>` carries data.

Forwarding is intentionally conservative:

- Unicast packets use the route table when possible.
- Route table updates prefer lower hop count, then require an RSSI margin before switching equal-hop routes.
- Duplicate data and route advertisements are dropped by `(src, mid)` / `(orig, mid)`.
- Broadcast control packets are dropped. Endpoint commands must be addressed to a specific endpoint.
- DTN is disabled for control payloads so stale movement or servo commands do not execute after route recovery.
- LoRa send defaults to listen-before-talk where the driver supports it.

## Endpoint Hardware

Endpoint software receives hardware capabilities from `toDevice/hardware/`.

Current capability:

- `servo`: MG90S-style PWM servo through `PwmServoActuator`.
- `servo`: optional Feetech-style bus servo through `BusServoActuator`.

The friend's repo had two incompatible servo approaches:

- `code_esp32_servo.py` used normal PWM on `board.D7`.
- `scservo.py` used UART packets for Feetech/SCServo bus servos on `TX=D7, RX=D6`.

MG90S is normally a PWM servo. The Seeed Bus Servo Driver Board is documented for ST/SC serial bus servos, so it may be the wrong board for MG90S. The firmware supports both modes, but the default is still PWM.

See `toDevice/hardware/ENDPOINT_SERVO_WIRING.md` before changing code. If the servo connector DATA pin is not directly connected to a XIAO `D*` pin, PWM mode cannot drive it.

## Friend Library Analysis

`toDevice/sx1262.py` is the friend's custom SX1262 CircuitPython driver. It is not a mesh library. It provides the radio operations this firmware depends on:

- SX1262 initialization for the project boards.
- RF switch integration.
- Fixed SF7 modulation settings.
- Async receive helpers such as `recv_start` and `recv_poll`.
- CAD/listen-before-talk support through `send_lbt`.
- RSSI and SNR access used by route and neighbor management.

For now, the library is necessary because the hardware and network layers rely on those driver behaviors. Replacing it is possible, but it should be treated as a separate hardware validation task: find an upstream SX1262 driver with equivalent RF switch, CAD/LBT, async RX, TCXO/LDO, RSSI, and SNR support, then field-test it on both board profiles.

The containment rule is that only `toDevice/hardware/` and `RadioAdapter` should depend on `sx1262.py`. Endpoint and network policy code should not import driver-specific APIs directly.
