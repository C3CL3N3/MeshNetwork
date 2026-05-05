# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Best-effort MicroPython SX1262 backend adapter.

This backend intentionally keeps imports lazy so host tests can run without machine/spi deps.
"""

from radio.backends.common import apply_initial_radio_settings, call_optional_driver_method


class SX1262MicroPythonBackend:
    def __init__(self, board_module, settings):
        self.board = board_module
        self.settings = dict(settings)
        self.initialized = False
        self.last_error = None
        self.spi = None
        self._driver = None

    def _pin_value(self, name):
        return getattr(self.board, name, None)

    def _build_spi(self, machine):
        sck = self._pin_value("SPI_SCK_PIN")
        mosi = self._pin_value("SPI_MOSI_PIN")
        miso = self._pin_value("SPI_MISO_PIN")
        if sck is None or mosi is None or miso is None:
            raise RuntimeError("board SPI pins are not configured")

        spi_id = getattr(self.board, "SPI_ID", 1)
        baud = int(self.settings.get("spi_baudrate", 2000000))
        return machine.SPI(
            spi_id,
            baudrate=baud,
            polarity=0,
            phase=0,
            sck=machine.Pin(sck),
            mosi=machine.Pin(mosi),
            miso=machine.Pin(miso),
        )

    def _driver_ctor(self):
        try:
            from sx1262 import SX1262  # type: ignore

            return SX1262
        except Exception:
            pass
        try:
            from sx126x import SX1262  # type: ignore

            return SX1262
        except Exception:
            pass
        return None

    def _build_driver(self):
        ctor = self._driver_ctor()
        if ctor is None:
            raise RuntimeError("SX1262 driver module not found (expected sx1262 or sx126x)")

        cs_pin = self._pin_value("LORA_CS_PIN")
        rst_pin = self._pin_value("LORA_RESET_PIN")
        busy_pin = self._pin_value("LORA_BUSY_PIN")
        dio1_pin = self._pin_value("LORA_DIO1_PIN")

        try:
            return ctor(
                spi=self.spi,
                cs=cs_pin,
                reset=rst_pin,
                busy=busy_pin,
                dio1=dio1_pin,
                freq=self.settings.get("frequency_hz", 923000000),
                bw=self.settings.get("bandwidth_hz", 125000),
                cr=self.settings.get("coding_rate", 5),
                sf=self.settings.get("spreading_factor", 9),
            )
        except TypeError:
            # Alternate constructor styles in different community libs.
            return ctor(self.spi, cs_pin, rst_pin, busy_pin, dio1_pin)

    def initialize(self):
        try:
            import machine  # type: ignore

            self.spi = self._build_spi(machine)
            self._driver = self._build_driver()
            apply_initial_radio_settings(self)
            self.initialized = True
            self.last_error = None
            return True
        except Exception as exc:
            self.initialized = False
            self.last_error = str(exc)
            return False

    def _call_driver(self, names, *args, **kwargs):
        return call_optional_driver_method(self._driver, names, *args, **kwargs)

    def set_frequency(self, freq_hz):
        self.settings["frequency_hz"] = int(freq_hz)
        self._call_driver(("set_frequency", "setFrequency", "frequency"), int(freq_hz))

    def set_bandwidth(self, bandwidth_hz):
        self.settings["bandwidth_hz"] = int(bandwidth_hz)
        self._call_driver(("set_bandwidth", "setBandwidth", "bandwidth"), int(bandwidth_hz))

    def set_coding_rate(self, coding_rate):
        self.settings["coding_rate"] = int(coding_rate)
        self._call_driver(("set_coding_rate", "setCodingRate", "coding_rate"), int(coding_rate))

    def set_spreading_factor(self, sf):
        self.settings["spreading_factor"] = int(sf)
        self._call_driver(("set_spreading_factor", "setSpreadingFactor", "spreading_factor"), int(sf))

    def send_packet(self, data):
        if self._driver is None:
            return False
        payload = data if isinstance(data, (bytes, bytearray)) else bytes(data)
        result = self._call_driver(("send", "send_packet", "transmit"), payload)
        if result is None:
            return False
        return bool(result)

    def receive_packet(self, timeout_ms=0):
        if self._driver is None:
            return None
        out = self._call_driver(("recv", "receive", "receive_packet"), int(timeout_ms))
        if out is None:
            return None
        if isinstance(out, tuple) and out:
            return out[0]
        return out

    def get_rssi(self):
        out = self._call_driver(("get_rssi", "rssi", "packet_rssi"))
        return out

    def get_snr(self):
        out = self._call_driver(("get_snr", "snr", "packet_snr"))
        return out

    def cad(self):
        out = self._call_driver(("cad", "channel_activity_detect", "is_channel_active"))
        if out is None:
            return False
        return bool(out)
