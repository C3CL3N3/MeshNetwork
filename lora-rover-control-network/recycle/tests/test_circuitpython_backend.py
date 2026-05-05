# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

import types

from radio.backends.sx1262_circuitpython import SX1262CircuitPythonBackend


class _BoardCfg:
    SPI_SCK_PIN = "SCK"
    SPI_MOSI_PIN = "MOSI"
    SPI_MISO_PIN = "MISO"
    LORA_CS_PIN = "D5"
    LORA_RESET_PIN = "D6"
    LORA_BUSY_PIN = "D9"
    LORA_DIO1_PIN = "D10"


def test_circuitpython_backend_init_fails_gracefully_without_runtime():
    backend = SX1262CircuitPythonBackend(_BoardCfg, {"frequency_hz": 923000000})

    ok = backend.initialize()

    assert ok is False
    assert backend.initialized is False
    assert backend.last_error is not None


def test_circuitpython_backend_pin_resolution_accepts_direct_pin_objects(monkeypatch):
    board = types.SimpleNamespace(SCK=object())

    class _Cfg:
        SPI_SCK_PIN = board.SCK

    backend = SX1262CircuitPythonBackend(_Cfg, {})
    backend.board = board

    assert backend._board_pin("SPI_SCK_PIN") is board.SCK


def test_circuitpython_backend_pin_resolution_accepts_integer_pin_ids():
    board = types.SimpleNamespace(IO36=object())

    class _Cfg:
        SPI_SCK_PIN = 36

    backend = SX1262CircuitPythonBackend(_Cfg, {})
    backend.board = board

    assert backend._board_pin("SPI_SCK_PIN") is board.IO36


def test_circuitpython_backend_pin_resolution_uses_first_valid_candidate():
    board = types.SimpleNamespace(D8=object())

    class _Cfg:
        SPI_SCK_PIN = ("NOPE", "D8", 36)

    backend = SX1262CircuitPythonBackend(_Cfg, {})
    backend.board = board

    assert backend._board_pin("SPI_SCK_PIN") is board.D8


def test_circuitpython_backend_constructor_fallback_supports_lab_style_signature():
    calls = {"count": 0, "begin": 0}

    class _Driver:
        def __init__(self, *args, **kwargs):
            calls["count"] += 1
            # Reject keyword form to emulate "unexpected keyword argument 'spi'".
            if "spi" in kwargs:
                raise TypeError("unexpected keyword argument 'spi'")
            # Accept only lab-style 8 positional args.
            if len(args) == 8:
                return
            raise TypeError("signature mismatch")

        def begin(self, *args, **kwargs):
            calls["begin"] += 1

    backend = SX1262CircuitPythonBackend(_BoardCfg, {"frequency_hz": 923000000})
    backend.spi = object()
    backend.digitalio = types.SimpleNamespace(DigitalInOut=lambda pin: ("dio", pin))
    backend._driver_ctor = lambda: _Driver
    backend._setup_rf_switch = lambda: None

    board = types.SimpleNamespace(SCK=object(), MOSI=object(), MISO=object(), D5=object(), D6=object(), D9=object(), D10=object())
    backend.board = board

    driver = backend._build_driver()

    assert driver is not None
    assert calls["count"] >= 1
    assert calls["begin"] == 1


def test_circuitpython_backend_prefers_raw_constructor_when_dio_pins_busy():
    class _Driver:
        def __init__(self, *args, **kwargs):
            if len(args) == 8:
                return
            raise TypeError("signature mismatch")

        def begin(self, *args, **kwargs):
            return None

    backend = SX1262CircuitPythonBackend(_BoardCfg, {"frequency_hz": 923000000})
    backend.spi = object()
    backend._driver_ctor = lambda: _Driver
    backend._setup_rf_switch = lambda: None
    backend.digitalio = types.SimpleNamespace(
        DigitalInOut=lambda pin: (_ for _ in ()).throw(RuntimeError("D4 in use"))
    )
    backend.board = types.SimpleNamespace(
        SCK=object(),
        MOSI=object(),
        MISO=object(),
        D1=object(),
        D4=object(),
        D5=object(),
        D6=object(),
        D9=object(),
        D10=object(),
    )

    driver = backend._build_driver()

    assert driver is not None


def test_circuitpython_backend_receive_tries_alternate_method_on_typeerror():
    class _Driver:
        def receive(self, a, b, c, d):
            return None

        def recv(self, timeout_ms):
            return b"ok"

    backend = SX1262CircuitPythonBackend(_BoardCfg, {})
    backend._driver = _Driver()

    out = backend.receive_packet(timeout_ms=5)

    assert out == b"ok"


def test_circuitpython_backend_receive_ignores_non_packet_tuple_values():
    class _Driver:
        def recv(self, timeout_ms):
            return ("ERR_CHIP_NOT_FOUND", -1)

    backend = SX1262CircuitPythonBackend(_BoardCfg, {})
    backend._driver = _Driver()

    out = backend.receive_packet(timeout_ms=5)

    assert out is None


def test_circuitpython_backend_receive_accepts_packet_in_tuple():
    class _Driver:
        def recv(self, timeout_ms):
            return (None, b"", b"pkt")

    backend = SX1262CircuitPythonBackend(_BoardCfg, {})
    backend._driver = _Driver()

    out = backend.receive_packet(timeout_ms=5)

    assert out == b"pkt"


def test_circuitpython_backend_pin_resolution_avoids_conflict_with_used_pin():
    shared = object()
    board = types.SimpleNamespace(D1=shared, D2=object())

    class _Cfg:
        LORA_RESET_PIN = ("D1", "D2")

    backend = SX1262CircuitPythonBackend(_Cfg, {})
    backend.board = board

    pin = backend._board_pin("LORA_RESET_PIN", avoid={shared})

    assert pin is board.D2
