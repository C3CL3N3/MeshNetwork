# SPDX-License-Identifier: MIT

import time

from software import config
from software.endpoints.base import BaseEndpoint


class GadgetEndpoint(BaseEndpoint):
    """Generic addressed endpoint.

    The endpoint owns software policy.
    Hardware capabilities are injected from the hardware layer.
    """

    def __init__(self, capabilities=None):
        self.capabilities = capabilities or {}
        self.debug_enabled = False
        self.debug_target = int(config.ENDPOINT_DEBUG_TARGET_NODE)
        self._last_debug_s = time.monotonic()

    def on_data(self, packet, mesh):
        if packet.dst != mesh.node_id:
            return
        payload = str(packet.payload)
        print("DELIVER endpoint src={0} dst={1}: '{2}'".format(packet.src, packet.dst, payload))

        if payload == "PING":
            mesh.send_data(packet.src, "ACK:PING:{0}".format(mesh.node_id), allow_dtn=False)
            return
        if payload == "CAPS?":
            caps = ",".join(sorted(self.capabilities.keys())) or "none"
            mesh.send_data(packet.src, "CAPS:{0}:{1}".format(mesh.node_id, caps), allow_dtn=False)
            return
        if payload.startswith("SERVO:"):
            self._handle_servo(packet, mesh, payload)
            return
        if self._is_control_command(payload):
            self._handle_control_command(payload, packet.src, mesh)
            return
        if payload.startswith("ENDPOINT:DEBUG"):
            self._handle_debug_command(payload, packet.src, mesh)
            return
        if payload.startswith("CMD:") or payload.startswith("ENDPOINT:"):
            mesh.send_data(packet.src, "ERROR:ENDPOINT:UNSUPPORTED", allow_dtn=False)

    def tick(self, mesh):
        if not self.debug_enabled:
            return
        now = time.monotonic()
        if now - self._last_debug_s < config.ENDPOINT_DEBUG_INTERVAL_S:
            return
        self._last_debug_s = now
        mesh.send_data(self.debug_target, "P{0}".format(int(now)), allow_dtn=False)

    def on_local_command(self, command, mesh):
        text = str(command).strip()
        if not text:
            return False
        if text.startswith("DEBUG"):
            if ":" in text:
                text = "ENDPOINT:" + text
            else:
                text = text.replace("DEBUG ", "ENDPOINT:DEBUG:", 1)
                if text == "DEBUG":
                    text = "ENDPOINT:DEBUG:ON"
            self._handle_debug_command(text, mesh.node_id, mesh)
            return True
        return False

    def _handle_servo(self, packet, mesh, payload):
        servo = self.capabilities.get("servo")
        if servo is None:
            mesh.send_data(packet.src, "ERROR:SERVO:NO_CAPABILITY", allow_dtn=False)
            return

        parts = payload[6:].split(":")
        angle_text = parts[-1]
        try:
            angle = servo.move_angle(
                float(angle_text),
                min_angle=config.ENDPOINT_SERVO_MIN_ANGLE,
                max_angle=config.ENDPOINT_SERVO_MAX_ANGLE,
            )
        except Exception:
            mesh.send_data(packet.src, "ERROR:SERVO:BAD_ANGLE", allow_dtn=False)
            return

        print("endpoint servo angle={0:.1f}".format(angle))
        mesh.send_data(packet.src, "ACK:SERVO:{0:.1f}".format(angle), allow_dtn=False)

    def _is_control_command(self, payload):
        text = str(payload or "").strip().upper()
        if not text:
            return False
        if text in ("F", "B", "L", "R", "S", "+", "-", "FORWARD", "BACKWARD",
                    "LEFT", "RIGHT", "STOP", "FWRD", "BACK", "RGHT"):
            return True
        return text.startswith(("H:", "V:", "HEADING:", "SPEED:", "F:", "B:", "FWD:", "BACK:"))

    def _validate_control_command(self, payload):
        text = str(payload or "").strip()
        upper = text.upper()
        if upper in ("F", "B", "L", "R", "S", "+", "-", "FORWARD", "BACKWARD",
                     "LEFT", "RIGHT", "STOP", "FWRD", "BACK", "RGHT"):
            return True
        try:
            if upper.startswith(("H:", "HEADING:", "V:", "SPEED:")):
                return float(text.split(":", 1)[1]) == float(text.split(":", 1)[1])
            if upper.startswith(("F:", "B:", "FWD:", "BACK:")):
                return int(float(text.split(":", 1)[1])) >= 0
        except Exception:
            return False
        return False

    def _handle_control_command(self, payload, reply_dst, mesh):
        text = str(payload or "").strip()
        if not self._validate_control_command(text):
            self._reply(reply_dst, "ERROR:CTRL:{0}".format(text), mesh)
            return
        print("endpoint ctrl cmd='{0}'".format(text))
        self._reply(reply_dst, "ACK:CTRL:{0}".format(text), mesh)

    def _handle_debug_command(self, payload, reply_dst, mesh):
        parts = payload.split(":")
        if len(parts) < 3:
            self._reply(reply_dst, "ERROR:DEBUG:BAD_FORMAT", mesh)
            return
        action = parts[2]
        if action == "ON":
            if len(parts) > 3:
                try:
                    self.debug_target = int(parts[3])
                except ValueError:
                    self._reply(reply_dst, "ERROR:DEBUG:BAD_TARGET", mesh)
                    return
            self.debug_enabled = True
            self._last_debug_s = time.monotonic() - config.ENDPOINT_DEBUG_INTERVAL_S
            self._reply(reply_dst, "ACK:DEBUG:ON:{0}".format(self.debug_target), mesh)
            return
        if action == "OFF":
            self.debug_enabled = False
            self._reply(reply_dst, "ACK:DEBUG:OFF", mesh)
            return
        if action == "STATUS":
            state = "ON" if self.debug_enabled else "OFF"
            self._reply(reply_dst, "DEBUG:{0}:{1}".format(state, self.debug_target), mesh)
            return
        self._reply(reply_dst, "ERROR:DEBUG:BAD_ACTION", mesh)

    def _reply(self, reply_dst, payload, mesh):
        if int(reply_dst) == int(mesh.node_id):
            print(payload)
            return
        mesh.send_data(reply_dst, payload, allow_dtn=False)
