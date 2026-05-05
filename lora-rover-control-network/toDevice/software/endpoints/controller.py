# SPDX-License-Identifier: MIT

from software.endpoints.base import BaseEndpoint


class ControllerEndpoint(BaseEndpoint):
    def on_data(self, packet, mesh):
        _ = mesh
        print("DELIVER controller src={0} dst={1}: '{2}'".format(packet.src, packet.dst, packet.payload))
        if str(packet.payload).startswith("PARROT:"):
            mesh.send_data(packet.src, "PONG:{0}:{1}".format(mesh.node_id, str(packet.payload)[7:]), allow_dtn=False)

