# SPDX-License-Identifier: MIT


class BaseEndpoint:
    def tick(self, mesh):
        _ = mesh

    def on_data(self, packet, mesh):
        _ = packet
        _ = mesh

    def on_local_command(self, command, mesh):
        _ = command
        _ = mesh
        return False
