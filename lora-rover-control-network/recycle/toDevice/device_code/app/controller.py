# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

from app.base import BaseApp


class SimpleControllerApp(BaseApp):
    """Simple controller: terminal text -> raw LoRa, raw LoRa -> terminal logs."""

    def __init__(self, radio, logger):
        super().__init__(radio, logger)
        self.node_id = 0
        self._input_buffer = ""

    def setup(self, runtime):
        super().setup(runtime)
        self.node_id = int(runtime.node_id)
        self.logger.info("Simple controller ready node=%s", self.node_id)
        self._send_text("BOOT: node {0} online".format(self.node_id))

    def _send_text(self, text):
        payload = str(text).encode("utf-8")
        tx_mode = getattr(self.radio, "set_tx_mode", None)
        rx_mode = getattr(self.radio, "set_rx_mode", None)
        if callable(tx_mode):
            tx_mode()
        try:
            ok = self.radio.send_packet(payload)
            self.logger.info("[TX] %s ok=%s", text, ok)
        finally:
            if callable(rx_mode):
                rx_mode()

    def _read_supervisor_line(self):
        try:
            import supervisor  # type: ignore
            import sys

            count = int(getattr(supervisor.runtime, "serial_bytes_available", 0))
            if count <= 0:
                return None
            chunk = sys.stdin.read(count)
            if not chunk:
                return None
            self._input_buffer += str(chunk)
            if "\n" not in self._input_buffer and "\r" not in self._input_buffer:
                return None
            line = self._input_buffer.replace("\r", "").replace("\n", "").strip()
            self._input_buffer = ""
            return line if line else None
        except Exception:
            return None

    def on_packet(self, packet):
        text = ""
        if isinstance(packet, (bytes, bytearray, memoryview)):
            try:
                text = bytes(packet).decode("utf-8", errors="ignore").strip()
            except Exception:
                text = ""
        if not text:
            self.logger.warn("[RX] non-text packet")
            return

        get_rssi = getattr(self.radio, "get_rssi", None)
        get_snr = getattr(self.radio, "get_snr", None)
        rssi = get_rssi() if callable(get_rssi) else None
        snr = get_snr() if callable(get_snr) else None
        self.logger.info("[RX] %s | RSSI=%s | SNR=%s", text, rssi, snr)

    def tick(self):
        line = self._read_supervisor_line()
        if line is None:
            return
        if line.upper() == "STATUS":
            self.logger.info("STATUS node=%s", self.node_id)
            return
        self._send_text(line)
