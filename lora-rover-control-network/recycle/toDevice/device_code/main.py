# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Prompt 1 main loop skeleton for multi-role LoRa node firmware."""

from config import LOOP_SLEEP_MS, RADIO_RECEIVE_TIMEOUT_MS
from runtime_config import get_runtime_config
from support.logger import get_logger
from radio.lora_iface import LoRaInterface

from recycle.toDevice.device_code.controller import ControllerApp
from toDevice.device_code.app.relay import RelayApp
#from toDevice.device_code.app.endpoint import EndApp


def _build_role_app(role_name, radio, logger):
    if role_name == "controller":
        return ControllerApp(radio, logger)
    if role_name == "relay":
        return RelayApp(radio, logger, forward=True)
    if role_name == "observer":
        return RelayApp(radio, logger, forward=False)
    return ControllerApp(radio, logger)


def _sleep_ms(ms):
    try:
        import time

        time.sleep(ms / 1000.0)
    except Exception:
        # Keep the scaffold tolerant across MicroPython/CPython variants.
        pass


def _log_radio_diagnostics(logger, radio):
    diag = radio.diagnostics()
    logger.info(
        "RADIO CHECK backend=%s board=%s initialized=%s spi=%s driver=%s sf=%s last_error=%s",
        diag["backend"],
        diag["board_profile"],
        diag["initialized"],
        diag["has_spi"],
        diag["has_driver"],
        diag["spreading_factor"],
        diag["last_error"],
    )


def main():
    logger = get_logger("main")
    runtime = get_runtime_config()

    radio = LoRaInterface(board_profile=runtime.board_profile)
    radio.initialize()
    _log_radio_diagnostics(logger, radio)

    app = _build_role_app(runtime.role, radio, logger)
    app.setup(runtime)

    logger.info("Node started: role=%s node_id=%s", runtime.role, runtime.node_id)

    while True:
        app.tick()

        incoming = radio.receive_packet(timeout_ms=RADIO_RECEIVE_TIMEOUT_MS)
        if incoming is not None:
            logger.info("Received a packet.")
            app.on_packet(incoming)

        _sleep_ms(LOOP_SLEEP_MS)


if __name__ == "__main__":
    main()
