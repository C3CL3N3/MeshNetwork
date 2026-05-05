# SPDX-License-Identifier: MIT


class RadioAdapter:
    """Thin wrapper around HardwarePlatform.lora.

    Uses advanced sx1262 methods when present and falls back to blocking calls.
    """

    def __init__(self, hardware):
        self.hardware = hardware

    def send(self, packet_bytes, use_lbt=False):
        radio = self.hardware.lora
        if radio is None:
            return False
        try:
            if use_lbt and hasattr(radio, "send_lbt"):
                ok = radio.send_lbt(packet_bytes, max_tries=3, base_backoff_ms=20)
            else:
                radio.send(packet_bytes)
                ok = True
            if hasattr(radio, "recv_start"):
                radio.recv_start()
            return bool(ok)
        except Exception as exc:
            print("radio tx err: {0}".format(exc))
            try:
                if hasattr(radio, "recv_start"):
                    radio.recv_start()
            except Exception:
                pass
            return False

    def start_rx(self):
        radio = self.hardware.lora
        if radio is not None and hasattr(radio, "recv_start"):
            try:
                radio.recv_start()
            except Exception:
                pass

    def poll(self, timeout_ms=300):
        radio = self.hardware.lora
        if radio is None:
            return None
        try:
            polled_async = hasattr(radio, "recv_poll")
            if hasattr(radio, "recv_poll"):
                result = radio.recv_poll()
                if result is None:
                    return None
            else:
                result = radio.recv(timeout_en=True, timeout_ms=int(timeout_ms))
            if not (result and isinstance(result, tuple) and result[0]):
                if polled_async and hasattr(radio, "recv_start"):
                    radio.recv_start()
                return None
            if polled_async and hasattr(radio, "recv_start"):
                radio.recv_start()
            return result[0]
        except Exception as exc:
            print("radio rx err: {0}".format(exc))
            try:
                if hasattr(radio, "recv_start"):
                    radio.recv_start()
            except Exception:
                pass
            return None

    def rssi(self):
        try:
            return self.hardware.lora.getRSSI()
        except Exception:
            return -999

    def snr(self):
        try:
            return self.hardware.lora.getSNR()
        except Exception:
            return 0.0
