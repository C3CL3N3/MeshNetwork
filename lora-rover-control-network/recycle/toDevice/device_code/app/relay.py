# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

from app.base import BaseApp


class RelayApp(BaseApp):
    """Simple relay: receive raw packets and forward once."""

    def __init__(self, radio, logger, forward=True):
        super().__init__(radio, logger)
        self.node_id = 0
        self.forward = bool(forward)
        self._recent = []
        self._recent_cap = 64

    def setup(self, runtime):
        super().setup(runtime)
        self.node_id = int(runtime.node_id)
        self.logger.info("Simple relay ready node=%s forward=%s", self.node_id, self.forward)

    def _remember(self, packet):
        key = bytes(packet)
        if key in self._recent:
            return False
        self._recent.append(key)
        if len(self._recent) > self._recent_cap:
            self._recent = self._recent[-self._recent_cap :]
        return True

    def _forward(self, packet):
        tx_mode = getattr(self.radio, "set_tx_mode", None)
        rx_mode = getattr(self.radio, "set_rx_mode", None)
        if callable(tx_mode):
            tx_mode()
        try:
            return self.radio.send_packet(packet)
        finally:
            if callable(rx_mode):
                rx_mode()

    def on_packet(self, packet):
        if not isinstance(packet, (bytes, bytearray, memoryview)):
            return
        payload = bytes(packet)
        if not payload:
            return

        if not self._remember(payload):
            self.logger.info("[RELAY] duplicate dropped")
            return

        text = payload.decode("utf-8", errors="ignore").strip()
        self.logger.info("[RELAY RX] %s", text if text else "<binary>")
        if self.forward:
            ok = self._forward(payload)
            self.logger.info("[RELAY TX] forwarded=%s", ok)
        else:
            self.logger.info("[RELAY OBSERVE] forward disabled")

    def tick(self):
        return None
