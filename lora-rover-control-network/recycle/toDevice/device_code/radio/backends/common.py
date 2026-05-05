# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Shared helpers for adaptive SX1262 backend wrappers."""


def call_optional_driver_method(driver, names, *args, **kwargs):
    if driver is None:
        return None
    last_type_error = None
    for name in names:
        fn = getattr(driver, name, None)
        if callable(fn):
            try:
                return fn(*args, **kwargs)
            except TypeError as exc:
                # Driver APIs vary across libraries; try next compatible method name.
                last_type_error = exc
                continue
    if last_type_error is not None:
        return None
    return None


def apply_initial_radio_settings(backend):
    backend.set_frequency(backend.settings.get("frequency_hz", 923000000))
    backend.set_bandwidth(backend.settings.get("bandwidth_hz", 125000))
    backend.set_coding_rate(backend.settings.get("coding_rate", 5))
    backend.set_spreading_factor(backend.settings.get("spreading_factor", 9))
