# SCServo / Feetech SCS-ST bus servo driver for CircuitPython
# Bus Servo Driver Board for XIAO: TX=D7, RX=D6, baudrate=1_000_000
#
# Packet format: [0xFF][0xFF][ID][LEN][INSTR][PARAMS...][CHECKSUM]
#   LEN      = len(params) + 2
#   CHECKSUM = ~(ID + LEN + INSTR + sum(params)) & 0xFF
#
# SCS series position register 0x2A: 0-4095, maps to 0-300 degrees.

import busio
import board
import time

_INSTR_PING       = 0x01
_INSTR_READ       = 0x02
_INSTR_WRITE      = 0x03
_INSTR_SYNC_WRITE = 0x83

_REG_GOAL_POS   = 0x2A   # 2 bytes: target position
_REG_GOAL_TIME  = 0x2C   # 2 bytes: move time (ms), 0 = max speed
_REG_GOAL_SPD   = 0x2E   # 2 bytes: goal speed (steps/s), 0 = no limit
_REG_TORQUE_EN  = 0x28   # 1 byte:  1=enabled, 0=free
_REG_PRESENT_POS = 0x38  # 2 bytes: current position (read)

# Servo range
POS_MIN   = 0
POS_MAX   = 4095
DEG_RANGE = 300.0    # total mechanical range of the servo in degrees


def _csum(data):
    return (~sum(data)) & 0xFF


def _build(servo_id, instr, params):
    length = len(params) + 2
    header = [servo_id, length, instr] + list(params)
    return bytes([0xFF, 0xFF] + header + [_csum(header)])


class SCServo:
    def __init__(self, tx_pin=board.D7, rx_pin=board.D6, baudrate=1_000_000):
        self._uart = busio.UART(tx_pin, rx_pin, baudrate=baudrate,
                                bits=8, parity=None, stop=1, timeout=0.05)

    def _send(self, pkt):
        self._uart.write(pkt)

    def _recv(self, n_bytes, timeout_ms=50):
        """Read up to n_bytes within timeout_ms. Returns bytes or None."""
        buf = bytearray()
        deadline = time.monotonic() + timeout_ms / 1000.0
        while len(buf) < n_bytes and time.monotonic() < deadline:
            chunk = self._uart.read(n_bytes - len(buf))
            if chunk:
                buf.extend(chunk)
        return bytes(buf) if buf else None

    # ── Write helpers ──────────────────────────────────────────────────────────

    def torque(self, servo_id, enable=True):
        """Enable or disable servo torque."""
        self._send(_build(servo_id, _INSTR_WRITE, [_REG_TORQUE_EN, int(enable)]))

    def write_pos(self, servo_id, position, move_time=0, speed=0):
        """
        Move servo to raw position (0-4095).
        move_time: ms to reach target (0 = as fast as possible).
        speed: steps/s (0 = no speed limit).
        """
        position = max(POS_MIN, min(POS_MAX, int(position)))
        params = [
            _REG_GOAL_POS,
            position & 0xFF, (position >> 8) & 0xFF,
            move_time & 0xFF, (move_time >> 8) & 0xFF,
            speed    & 0xFF, (speed     >> 8) & 0xFF,
        ]
        self._send(_build(servo_id, _INSTR_WRITE, params))

    def write_angle(self, servo_id, degrees, move_time=0, speed=0):
        """Move servo to degrees (0 to DEG_RANGE)."""
        pos = int(degrees / DEG_RANGE * POS_MAX)
        self.write_pos(servo_id, pos, move_time, speed)

    def sync_write(self, positions):
        """
        Move multiple servos simultaneously.
        positions: list of (servo_id, position, move_time, speed) tuples.
        """
        param_len = 6    # pos_l, pos_h, time_l, time_h, spd_l, spd_h
        params = [_REG_GOAL_POS, param_len]
        for sid, pos, mt, spd in positions:
            pos = max(POS_MIN, min(POS_MAX, int(pos)))
            params += [sid,
                       pos & 0xFF, (pos >> 8) & 0xFF,
                       mt  & 0xFF, (mt  >> 8) & 0xFF,
                       spd & 0xFF, (spd >> 8) & 0xFF]
        self._send(_build(0xFE, _INSTR_SYNC_WRITE, params))  # 0xFE = broadcast

    # ── Read helpers ───────────────────────────────────────────────────────────

    def read_pos(self, servo_id):
        """Return current position (0-4095) or None on timeout."""
        self._send(_build(servo_id, _INSTR_READ, [_REG_PRESENT_POS, 0x02]))
        resp = self._recv(8)
        if resp and len(resp) >= 8 and resp[0] == 0xFF and resp[1] == 0xFF:
            return resp[5] | (resp[6] << 8)
        return None

    def read_angle(self, servo_id):
        """Return current angle in degrees or None."""
        pos = self.read_pos(servo_id)
        return round(pos / POS_MAX * DEG_RANGE, 1) if pos is not None else None

    def ping(self, servo_id):
        """Return True if servo responds."""
        self._send(_build(servo_id, _INSTR_PING, []))
        resp = self._recv(6)
        return bool(resp and len(resp) >= 6 and resp[0] == 0xFF and resp[1] == 0xFF)
