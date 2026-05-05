`code.py` and `code2.py` are from labs and can be deleted basically. I used them to construct hardware layer classes.

What we need now:
We need the Software layer with network that inherits from hardware layer that would provide more complex functionality. 
- In Software layer we process the packets and understand the commands. Also here we differentiate the different roles of the nodes (sender, relay, endpoint).
- Network layer implements our mesh network coordination, management and forwarding.

`recycle/` provides some old code for the network. However, the connection layer was not organized and did not work, therefore I had to nuclear everything and build the hardware layer on my own.

I think there is still a lot of usable functionality in the `recycle/` folder that we need to translate to the Software-Network layer architecture (more precisely in the `recycle/toDevice` folder). The old rover-specific code should be treated as endpoint reference material only.

Current develop direction:

- `hardware/` remains the board-specific layer for pins, SX1262 setup, BLE helpers, RF switch control, and serial input.
- `software/protocol/` implements the fixed-SF7 H/R/D packet codec compatible with the `MeshNetwork cleanup-sf7` branch:
  - `H:<src>`
  - `R:<orig>:<fwd>:<mid>:<hops>`
  - `D:<src>:<dst>:<next_hop>:<mid>:<ttl>:<payload>`
- `software/network/` implements neighbor tracking, route tracking with hysteresis, deduplication, DTN queueing for non-control packets, radio adaptation, and forwarding.
- `software/endpoints/` implements role behavior:
  - `controller`
  - `relay`
  - `endpoint`
- `software/gateway/` contains the BLE dashboard bridge.
- `sx1262.py` is included in `toDevice/` so the deployment package has the fixed-SF7 branch's CAD/LBT-capable radio driver.
- `code.py` is now a role-based entrypoint. Edit `GROUP_ID`, `NODE_ID`, `BOARD_PROFILE`, and `ROLE` in `software/config.py` or override them in `code.py` before deployment.
- Only the `controller` role accepts BLE or serial application commands. Relay and endpoint nodes still participate in H/R/D mesh management but do not originate arbitrary user traffic.
- `dashboard/` contains the provided website adapted to flash this structured firmware tree instead of the friend's monolithic `code_*.py` files.

Important policy:

- DTN is disabled for control-style payloads such as `SERVO:` endpoint actuation commands. Actuation commands must not execute late after a route recovers.
- Broadcast control packets are dropped. Endpoint commands should be addressed to a specific endpoint node.
- Keep fixed SF7 until routing, endpoint safety, ACK behavior, and field testing are stable.
- Adaptive SF should remain future work, not part of the first reliable endpoint-control build.

Driver note:

- The friend's `sx1262.py` is currently useful and likely necessary because it provides SX1262 setup, RF-switch support, async RX polling, CAD/listen-before-talk, RSSI, and SNR. Keep it isolated behind the hardware layer and `software/network/radio_adapter.py`; endpoint code should not import it directly.
- Servo control is implemented as a hardware capability in `hardware/actuators.py`, then injected into the generic software endpoint. Use `ENDPOINT_ACTUATOR = "pwm_servo"` for MG90S-style PWM. Use `ENDPOINT_ACTUATOR = "bus_servo"` only for Feetech/ST/SC serial bus servos. See `hardware/ENDPOINT_SERVO_WIRING.md`.
