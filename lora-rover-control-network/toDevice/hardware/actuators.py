# SPDX-License-Identifier: MIT


class PwmServoActuator:
    """Hardware-layer PWM servo wrapper.

    This is for a normal PWM servo such as MG90S.
    It is not for SCServo / Feetech bus servos.
    """

    def __init__(self, pin_name="D7", min_us=500, max_us=2500, frequency=50):
        import board
        import pwmio

        self.pin_name = str(pin_name)
        self.min_us = int(min_us)
        self.max_us = int(max_us)
        self.frequency = int(frequency)
        pin = getattr(board, self.pin_name)
        self._period_us = 1000000 // self.frequency
        self._pwm = pwmio.PWMOut(pin, frequency=self.frequency, duty_cycle=0)
        self.angle = None

    def move_angle(self, angle, min_angle=0, max_angle=180):
        angle = max(float(min_angle), min(float(max_angle), float(angle)))
        pulse_us = self.min_us + (angle / 180.0) * (self.max_us - self.min_us)
        self._pwm.duty_cycle = int(pulse_us / self._period_us * 65535)
        self.angle = angle
        return angle

    def deinit(self):
        self._pwm.deinit()


def _checksum(data):
    return (~sum(data)) & 0xFF


def _packet(servo_id, instruction, params):
    length = len(params) + 2
    body = [int(servo_id), length, int(instruction)] + list(params)
    return bytes([0xFF, 0xFF] + body + [_checksum(body)])


class BusServoActuator:
    """UART bus-servo wrapper for Feetech SC/ST-style servos.

    This is not for MG90S PWM servos.
    Wiring is crossed: host TX -> driver RX, host RX <- driver TX.
    """

    _INSTR_PING = 0x01
    _INSTR_WRITE = 0x03
    _REG_GOAL_POS = 0x2A
    _REG_TORQUE_EN = 0x28

    def __init__(self, tx_pin_name="D7", rx_pin_name="D6", baudrate=1000000, servo_id=1):
        import board
        import busio

        self.tx_pin_name = str(tx_pin_name)
        self.rx_pin_name = str(rx_pin_name)
        self.baudrate = int(baudrate)
        self.servo_id = int(servo_id)
        self._uart = busio.UART(
            getattr(board, self.tx_pin_name),
            getattr(board, self.rx_pin_name),
            baudrate=self.baudrate,
            bits=8,
            parity=None,
            stop=1,
            timeout=0.05,
        )
        self.angle = None

    def _send(self, packet):
        self._uart.write(packet)

    def ping(self):
        self._send(_packet(self.servo_id, self._INSTR_PING, []))
        reply = self._uart.read(6)
        return bool(reply and len(reply) >= 6 and reply[0] == 0xFF and reply[1] == 0xFF)

    def torque(self, enable=True):
        self._send(_packet(self.servo_id, self._INSTR_WRITE, [self._REG_TORQUE_EN, int(enable)]))

    def move_angle(self, angle, min_angle=0, max_angle=180):
        angle = max(float(min_angle), min(float(max_angle), float(angle)))
        position = int(angle / 300.0 * 4095)
        params = [
            self._REG_GOAL_POS,
            position & 0xFF,
            (position >> 8) & 0xFF,
            0,
            0,
            0,
            0,
        ]
        self._send(_packet(self.servo_id, self._INSTR_WRITE, params))
        self.angle = angle
        return angle

    def deinit(self):
        self._uart.deinit()
