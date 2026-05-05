# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Role app base class."""


class BaseApp:
    def __init__(self, radio, logger):
        self.radio = radio
        self.logger = logger
        self.runtime = None

    def setup(self, runtime):
        self.runtime = runtime

    def on_packet(self, packet):
        _ = packet

    def tick(self):
        return None
