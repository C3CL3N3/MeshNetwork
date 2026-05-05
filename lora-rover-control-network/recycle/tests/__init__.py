# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Test package marker and import path bootstrap."""

import os
import sys


_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_TESTS_DIR)
_DEVICE_CODE_DIR = os.path.join(_ROOT_DIR, "toDevice", "device_code")

if _DEVICE_CODE_DIR not in sys.path:
    sys.path.insert(0, _DEVICE_CODE_DIR)
