# SPDX-License-Identifier: MIT

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "toDevice"))

import sx1262


class FakeTxRadio:
    send = sx1262.SX1262.send

    def __init__(self, irq=0):
        self.irq = irq
        self.commands = []
        self.force_standby_calls = 0
        self.rx_mode_calls = 0
        self.cleared_irq = 0
        self.written = []

    def _clr_irq(self, mask=0xFFFF):
        self.cleared_irq += 1

    def _set_irq(self, mask):
        self.irq_mask = mask

    def _write(self, data):
        self.written.append(bytes(data))

    def _cmd(self, opcode, *args):
        self.commands.append((opcode, args))

    def _tx_mode(self):
        self.tx_mode = True

    def _rx_mode(self):
        self.rx_mode_calls += 1

    def _poll_irq(self, mask, timeout_ms):
        self.poll_mask = mask
        self.poll_timeout_ms = timeout_ms
        return self.irq

    def _force_standby(self):
        self.force_standby_calls += 1


class Sx1262TxRecoveryTests(unittest.TestCase):
    def test_send_uses_finite_radio_timeout(self):
        radio = FakeTxRadio(irq=sx1262._IRQ_TX_DONE)

        radio.send(b"H:1", timeout_ms=5000)

        set_tx = [cmd for cmd in radio.commands if cmd[0] == sx1262._SET_TX]
        self.assertEqual(len(set_tx), 1)
        self.assertNotEqual(set_tx[0][1], (0, 0, 0))

    def test_send_forces_standby_on_host_tx_timeout(self):
        radio = FakeTxRadio(irq=0)

        with self.assertRaisesRegex(RuntimeError, "SX1262 TX timeout"):
            radio.send(b"H:1", timeout_ms=5000)

        self.assertGreaterEqual(radio.force_standby_calls, 1)


if __name__ == "__main__":
    unittest.main()
