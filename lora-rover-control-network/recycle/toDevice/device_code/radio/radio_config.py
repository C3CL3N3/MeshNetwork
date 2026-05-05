# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Radio configuration defaults and board profile lookup."""

from config import (
    BOARD_PROFILE,
    LORA_BANDWIDTH_HZ,
    LORA_CODING_RATE,
    LORA_DEFAULT_SF,
    LORA_FREQUENCY_HZ,
)


RADIO_DEFAULTS = {
    "frequency_hz": LORA_FREQUENCY_HZ,
    "bandwidth_hz": LORA_BANDWIDTH_HZ,
    "coding_rate": LORA_CODING_RATE,
    "spreading_factor": LORA_DEFAULT_SF,
}

BOARD_MODULES = {
    "generic": "boards.board_generic",
    "esp32s3_sx1262": "boards.board_esp32s3_sx1262",
    "nrf52840_sx1262": "boards.board_nrf52840_sx1262",
}


_PROFILE_ALIASES = {
    "esp32s3-sx1262": "esp32s3_sx1262",
    "esp32_s3_sx1262": "esp32s3_sx1262",
    "nrf52840-sx1262": "nrf52840_sx1262",
}


def normalize_board_profile(board_profile):
    if board_profile is None:
        board_profile = BOARD_PROFILE
    if not isinstance(board_profile, str):
        return "generic"

    key = board_profile.strip().lower().replace("-", "_")
    key = _PROFILE_ALIASES.get(key, key)
    if key in BOARD_MODULES:
        return key
    return "generic"


def load_board_module(board_profile=None):
    board_profile = normalize_board_profile(board_profile)
    if board_profile == "esp32s3_sx1262":
        import boards.board_esp32s3_sx1262 as mod

        return mod
    if board_profile == "nrf52840_sx1262":
        import boards.board_nrf52840_sx1262 as mod

        return mod
    import boards.board_generic as mod

    return mod

def radio_runtime_settings(**overrides):
    settings = dict(RADIO_DEFAULTS)
    settings.update(overrides)
    return settings
