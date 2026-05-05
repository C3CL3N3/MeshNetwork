# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Portable time helper."""


def ticks_ms():
    try:
        import time

        return int(time.time() * 1000)
    except Exception:
        return 0
