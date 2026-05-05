# SPDX-License-Identifier: MIT

from software.endpoints.base import BaseEndpoint


class RelayEndpoint(BaseEndpoint):
    def on_data(self, packet, mesh):
        _ = mesh
        print("DELIVER relay src={0} dst={1}: '{2}'".format(packet.src, packet.dst, packet.payload))

