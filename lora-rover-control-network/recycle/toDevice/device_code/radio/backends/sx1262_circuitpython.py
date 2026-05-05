# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""CircuitPython SX1262 backend adapter.

Targets CircuitPython environments using board/busio/digitalio and Adafruit-style SX1262 drivers.
This backend fails gracefully when dependencies or pin mappings are unavailable.
"""

from radio.backends.common import apply_initial_radio_settings, call_optional_driver_method


class SX1262CircuitPythonBackend:
    def __init__(self, board_module, settings):
        self.board_config = board_module
        self.settings = dict(settings)
        self.initialized = False
        self.last_error = None

        self.board = None
        self.busio = None
        self.digitalio = None
        self.spi = None
        self._driver = None

    def _import_runtime(self):
        import board  # type: ignore
        import busio  # type: ignore
        import digitalio  # type: ignore

        self.board = board
        self.busio = busio
        self.digitalio = digitalio

    def _driver_ctor(self):
        try:
            from adafruit_sx1262 import SX1262  # type: ignore

            return SX1262
        except Exception:
            pass
        try:
            from sx1262 import SX1262  # type: ignore

            return SX1262
        except Exception:
            pass
        return None

    def _resolve_pin_candidate(self, value):
        if value is None:
            return None
        if isinstance(value, int):
            candidates = (
                "IO{0}".format(value),
                "D{0}".format(value),
                "GPIO{0}".format(value),
                "GP{0}".format(value),
            )
            for candidate in candidates:
                pin = getattr(self.board, candidate, None)
                if pin is not None:
                    return pin
            raise RuntimeError(
                "board pin id not found: {0} (tried {1})".format(value, ", ".join(candidates))
            )
        if isinstance(value, str):
            pin = getattr(self.board, value, None)
            if pin is None:
                raise RuntimeError("board pin name not found: {0}".format(value))
            return pin
        return value

    def _board_pin(self, name, avoid=None):
        """Resolve CircuitPython pin object.

        Supported config forms:
        1) board pin object directly in board config
        2) string pin name in board config, e.g. "IO5" or "D10"
        3) integer pin id resolved via common board attrs (IOx, Dxx, GPIOxx, GPxx)
        4) tuple/list of candidates; first resolvable candidate is used
        """
        avoid = set() if avoid is None else set(avoid)
        value = getattr(self.board_config, name, None)
        if value is None:
            raise RuntimeError("missing board pin mapping: {0}".format(name))
        if isinstance(value, (list, tuple)):
            last_err = None
            for candidate in value:
                try:
                    pin = self._resolve_pin_candidate(candidate)
                except Exception as exc:
                    last_err = exc
                    continue
                if pin is not None and pin not in avoid:
                    return pin
            if last_err is not None:
                raise RuntimeError("no valid candidate for {0}: {1}".format(name, last_err))
            raise RuntimeError("no valid candidate for {0}".format(name))
        pin = self._resolve_pin_candidate(value)
        if pin in avoid:
            raise RuntimeError("pin conflict for {0}".format(name))
        return pin

    def _build_spi(self):
        sck = self._board_pin("SPI_SCK_PIN")
        mosi = self._board_pin("SPI_MOSI_PIN")
        miso = self._board_pin("SPI_MISO_PIN")
        return self.busio.SPI(clock=sck, MOSI=mosi, MISO=miso)

    def _dio(self, pin_name):
        pin = self._board_pin(pin_name)
        return self.digitalio.DigitalInOut(pin)

    def _setup_rf_switch(self):
        if not hasattr(self.board_config, "LORA_RF_SW_PIN"):
            return None
        try:
            rf = self._dio("LORA_RF_SW_PIN")
            rf.direction = self.digitalio.Direction.OUTPUT
            rf.value = False
            return rf
        except Exception:
            return None

    def _set_rf_switch(self, value):
        rf = getattr(self, "rf_switch", None)
        if rf is None:
            return False
        try:
            rf.value = bool(value)
            return True
        except Exception:
            return False

    def _try_begin(self, driver):
        begin = getattr(driver, "begin", None)
        if not callable(begin):
            return

        freq_hz = int(self.settings.get("frequency_hz", 923000000))
        freq_mhz = float(freq_hz) / 1000000.0
        bw_hz = int(self.settings.get("bandwidth_hz", 125000))
        bw_khz = float(bw_hz) / 1000.0
        sf = int(self.settings.get("spreading_factor", 9))
        cr = int(self.settings.get("coding_rate", 5))

        attempts = (
            lambda: begin(freq=freq_mhz, bw=bw_khz, sf=sf, cr=cr, useRegulatorLDO=True, tcxoVoltage=1.6),
            lambda: begin(freq=freq_mhz, bw=bw_khz, sf=sf, cr=cr),
            lambda: begin(freq_mhz, bw_khz, sf, cr),
        )
        for call in attempts:
            try:
                call()
                return
            except TypeError:
                continue

    def _build_driver(self):
        ctor = self._driver_ctor()
        if ctor is None:
            raise RuntimeError("SX1262 CircuitPython driver not found")

        self.rf_switch = self._setup_rf_switch()
        sck_pin = self._board_pin("SPI_SCK_PIN")
        mosi_pin = self._board_pin("SPI_MOSI_PIN", avoid={sck_pin})
        miso_pin = self._board_pin("SPI_MISO_PIN", avoid={sck_pin, mosi_pin})
        cs_pin = self._board_pin("LORA_CS_PIN", avoid={sck_pin, mosi_pin, miso_pin})
        reset_pin = self._board_pin("LORA_RESET_PIN", avoid={sck_pin, mosi_pin, miso_pin, cs_pin})
        busy_pin = self._board_pin("LORA_BUSY_PIN", avoid={sck_pin, mosi_pin, miso_pin, cs_pin, reset_pin})
        dio1_pin = self._board_pin("LORA_DIO1_PIN", avoid={sck_pin, mosi_pin, miso_pin, cs_pin, reset_pin, busy_pin})

        errors = []
        raw_attempts = (
            lambda: ctor(self.spi, sck_pin, mosi_pin, miso_pin, cs_pin, dio1_pin, reset_pin, busy_pin),
            lambda: ctor(self.spi, cs_pin, reset_pin, busy_pin, dio1_pin),
            lambda: ctor(spi=self.spi, sck=sck_pin, mosi=mosi_pin, miso=miso_pin, nss=cs_pin, dio1=dio1_pin, reset=reset_pin, busy=busy_pin),
        )
        for call in raw_attempts:
            try:
                driver = call()
                self._try_begin(driver)
                return driver
            except TypeError as exc:
                errors.append(str(exc))
                continue

        wrappers = None
        try:
            wrappers = (
                self.digitalio.DigitalInOut(cs_pin),
                self.digitalio.DigitalInOut(reset_pin),
                self.digitalio.DigitalInOut(busy_pin),
                self.digitalio.DigitalInOut(dio1_pin),
            )
            cs, reset, busy, dio1 = wrappers
            object_attempts = (
                lambda: ctor(self.spi, cs, reset, busy, dio1, self.settings.get("frequency_hz", 923000000)),
                lambda: ctor(spi=self.spi, cs=cs, reset=reset, busy=busy, dio1=dio1, frequency=self.settings.get("frequency_hz", 923000000)),
            )
            for call in object_attempts:
                try:
                    driver = call()
                    self._try_begin(driver)
                    return driver
                except TypeError as exc:
                    errors.append(str(exc))
                    continue
        except Exception as exc:
            errors.append(str(exc))
        finally:
            if wrappers is not None:
                for item in wrappers:
                    deinit = getattr(item, "deinit", None)
                    if callable(deinit):
                        deinit()

        raise RuntimeError("SX1262 driver constructor mismatch: {0}".format(" | ".join(errors)))

    def _call_driver(self, names, *args, **kwargs):
        return call_optional_driver_method(self._driver, names, *args, **kwargs)

    def initialize(self):
        try:
            self._import_runtime()
            self.spi = self._build_spi()
            self._driver = self._build_driver()
            apply_initial_radio_settings(self)
            self.initialized = True
            self.last_error = None
            return True
        except Exception as exc:
            self.initialized = False
            self.last_error = str(exc)
            return False

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
        payload = data if isinstance(data, (bytes, bytearray)) else bytes(data)
        out = self._call_driver(("send", "send_packet", "transmit"), payload)
        if out is None:
            return False
        return bool(out)

    def set_tx_mode(self):
        return self._set_rf_switch(True)

    def set_rx_mode(self):
        return self._set_rf_switch(False)

    def _as_packet_bytes(self, value):
        if isinstance(value, memoryview):
            value = value.tobytes()
        elif isinstance(value, bytearray):
            value = bytes(value)

        if isinstance(value, bytes):
            if len(value) == 0:
                return None
            return value
        return None

    def receive_packet(self, timeout_ms=0):
        out = self._call_driver(("receive", "recv", "receive_packet"), int(timeout_ms))
        if out is None:
            return None
        if isinstance(out, tuple):
            for item in out:
                pkt = self._as_packet_bytes(item)
                if pkt is not None:
                    return pkt
            return None
        return self._as_packet_bytes(out)

    def get_rssi(self):
        return self._call_driver(("rssi", "get_rssi", "packet_rssi"))

    def get_snr(self):
        return self._call_driver(("snr", "get_snr", "packet_snr"))

    def cad(self):
        out = self._call_driver(("cad", "is_channel_active", "channel_activity_detect"))
        if out is None:
            return False
        return bool(out)
