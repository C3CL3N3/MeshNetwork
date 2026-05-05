# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

import sys
sys.path.insert(0, "/device_code")
import runtime_config as r
import main

c = r.get_runtime_config()
c.parse_command("ROLE:controller")
c.parse_command("NODE:2")
c.parse_command("BOARD:esp32s3_sx1262")  # generic, esp32s3_sx1262 or nrf52840_sx1262
main.main()
