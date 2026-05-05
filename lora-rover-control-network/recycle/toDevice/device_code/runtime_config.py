# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Runtime configuration and serial-style command parsing."""

from config import BOARD_PROFILE, DEFAULT_MODE, DEFAULT_NODE_ID, DEFAULT_ROLE, VALID_BOARD_PROFILES, VALID_MODES, VALID_ROLES


class RuntimeConfig:
    def __init__(self):
        self.node_id = DEFAULT_NODE_ID
        self.role = DEFAULT_ROLE
        self.mode = DEFAULT_MODE
        self.board_profile = BOARD_PROFILE

    def parse_command(self, line):
        """Parse simple console commands and update runtime values.

        Supported commands:
        - ROLE:<controller|relay|rover|observer>
        - NODE:<int>
        - MODE:<speed|throughput>
        - BOARD:<generic|esp32s3_sx1262|nrf52840_sx1262>
        - STATUS
        """
        if line is None:
            return "ERR: empty"

        line = line.strip()
        if not line:
            return self.status()

        upper = line.upper()
        if upper == "STATUS":
            return self.status()

        if upper.startswith("ROLE:"):
            candidate = line.split(":", 1)[1].strip().lower()
            if candidate not in VALID_ROLES:
                return "ERR: invalid role"
            self.role = candidate
            return "OK"

        if upper.startswith("NODE:"):
            raw = line.split(":", 1)[1].strip()
            try:
                self.node_id = int(raw, 0)
            except ValueError:
                return "ERR: invalid node id"
            return "OK"

        if upper.startswith("MODE:"):
            candidate = line.split(":", 1)[1].strip().lower()
            if candidate not in VALID_MODES:
                return "ERR: invalid mode"
            self.mode = candidate
            return "OK"

        if upper.startswith("BOARD:"):
            candidate = line.split(":", 1)[1].strip().lower().replace("-", "_")
            if candidate not in VALID_BOARD_PROFILES:
                return "ERR: invalid board profile"
            self.board_profile = candidate
            return "OK"

        return "ERR: unknown command"

    def status(self):
        return "role={0} node_id={1} mode={2} board={3}".format(self.role, self.node_id, self.mode, self.board_profile)


_RUNTIME_CONFIG = RuntimeConfig()


def get_runtime_config():
    return _RUNTIME_CONFIG
