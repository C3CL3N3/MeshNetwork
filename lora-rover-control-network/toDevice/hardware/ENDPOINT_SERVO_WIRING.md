# Endpoint Servo Wiring Check

## First Identify The Servo Type

Check the label on the servo itself.

- `MG90S`, `SG90`, or three wires `GND/VCC/DATA` usually means a normal PWM servo.
- Feetech `SCS`, `STS`, `SC`, or a servo with an ID usually means a serial bus servo.

This matters because the control signal is different.

- PWM servo: one PWM signal wire. Use `ENDPOINT_ACTUATOR = "pwm_servo"`.
- Bus servo: UART packet protocol through the driver board. Use `ENDPOINT_ACTUATOR = "bus_servo"`.

If the servo is truly MG90S, the Seeed Bus Servo Driver Board is probably the wrong controller. It is designed for ST/SC serial bus servos, not normal PWM servos.

## TX/RX Naming

TX/RX are supposed to be crossed.

- ESP/XIAO TX goes to driver RX.
- ESP/XIAO RX goes to driver TX.

For the Seeed bus servo board docs, this usually means:

- host TX: `D7`
- host RX: `D6`

So seeing `D6` connected to `TX` and `D7` connected to `RX` can be correct. It depends which side the label is printed for.

## How To Find The DATA Pin

Do this physically.

1. Find the 3-pin servo output where the motor plugs in.
2. Read the printed labels beside the three pins.
3. The pins should be some form of `GND`, `VCC`, and `DATA` / `SIG` / `S`.
4. Follow the `DATA` trace or connector label back to the board.
5. If it goes only to the servo connector and not to any XIAO `D*` pin, it is not a direct ESP GPIO pin.
6. If it goes through the driver chip, then ESP controls it through UART, not PWM.
7. If it connects directly to a XIAO header pin, use that header label as `ENDPOINT_SERVO_PIN`.

If you cannot follow traces, use a multimeter continuity test:

1. Power everything off.
2. Put one probe on the servo connector `DATA` pin.
3. Touch the other probe to XIAO/ESP header pins `D0` to `D10`.
4. If one pin beeps, that is the direct PWM pin.
5. If none beep, DATA is behind the driver circuit and you need bus-servo mode or different hardware.

## Current Firmware Defaults

For normal MG90S PWM:

```python
ENDPOINT_ACTUATOR = "pwm_servo"
ENDPOINT_SERVO_PIN = "D7"
```

For Seeed/Feetech serial bus servos:

```python
ENDPOINT_ACTUATOR = "bus_servo"
ENDPOINT_BUS_SERVO_TX_PIN = "D7"
ENDPOINT_BUS_SERVO_RX_PIN = "D6"
ENDPOINT_BUS_SERVO_ID = 1
```

## Fast Test

Flash an ESP32 as `endpoint`.

From the controller, send addressed commands:

```text
TO:<endpoint_node_id>:CAPS?
TO:<endpoint_node_id>:SERVO:30
TO:<endpoint_node_id>:SERVO:120
TO:<endpoint_node_id>:ENDPOINT:DEBUG:ON:1
```

If the endpoint replies `ACK:SERVO` but the motor does not move, the firmware accepted the command but the actuator wiring/type is wrong.
