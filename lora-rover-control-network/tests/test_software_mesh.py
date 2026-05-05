# SPDX-License-Identifier: MIT

import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "toDevice"))

from software.network import MeshNetwork, RouteTable
from software.network.radio_adapter import RadioAdapter
from software.endpoints import GadgetEndpoint
from software.protocol import DataPacket, HelloPacket, PacketCodec, RouteAdPacket


class FakeRadio:
    def __init__(self, send_ok=True):
        self.sent = []
        self.inbox = []
        self._rssi = -70
        self._snr = 7.5
        self.send_ok = send_ok

    def send(self, packet_bytes, use_lbt=False):
        self.sent.append((packet_bytes, use_lbt))
        return self.send_ok

    def poll(self):
        if not self.inbox:
            return None
        return self.inbox.pop(0)

    def rssi(self):
        return self._rssi

    def snr(self):
        return self._snr


class FakeSink:
    def __init__(self):
        self.events = []

    def notify(self, msg):
        self.events.append(msg)


class FakeEndpoint:
    def __init__(self):
        self.delivered = []

    def tick(self, mesh):
        pass

    def on_data(self, packet, mesh):
        self.delivered.append((packet.src, packet.dst, packet.payload))


class FakeHardware:
    def __init__(self, lora):
        self.lora = lora


class FakeAsyncRadio:
    def __init__(self, result):
        self.result = result
        self.recv_starts = 0

    def recv_poll(self):
        return self.result

    def recv_start(self):
        self.recv_starts += 1


class FakeServo:
    def __init__(self):
        self.angles = []

    def move_angle(self, angle, min_angle=0, max_angle=180):
        angle = max(float(min_angle), min(float(max_angle), float(angle)))
        self.angles.append(angle)
        return angle


class PacketCodecTests(unittest.TestCase):
    def test_h_r_d_roundtrip(self):
        codec = PacketCodec()
        self.assertIsInstance(codec.decode(codec.encode_hello(2)), HelloPacket)
        self.assertIsInstance(codec.decode(codec.encode_route_ad(2, 3, 4, 1)), RouteAdPacket)
        route = codec.decode(codec.encode_route_ad(2, 3, 4, 1, -82, 9.5))
        self.assertEqual(route.path_rssi, -82)
        self.assertEqual(route.path_snr, 9.5)
        packet = codec.decode(codec.encode_data(1, 2, 3, 4, 5, "payload:with:colon"))
        self.assertIsInstance(packet, DataPacket)
        self.assertEqual(packet.payload, "payload:with:colon")


class RouteTableTests(unittest.TestCase):
    def test_hop_count_wins_and_rssi_tiebreaks(self):
        routes = RouteTable(rssi_margin_db=4)
        self.assertTrue(routes.update(5, 2, advertised_hops=2, link_rssi=-80, now_s=1))
        self.assertTrue(routes.update(5, 3, advertised_hops=1, link_rssi=-95, now_s=2))
        self.assertEqual(routes.next_hop(5), 3)
        self.assertFalse(routes.update(5, 4, advertised_hops=1, link_rssi=-93, now_s=3))
        self.assertTrue(routes.update(5, 4, advertised_hops=1, link_rssi=-85, now_s=4))
        self.assertEqual(routes.next_hop(5), 4)

    def test_reliable_prefers_stronger_path_over_shorter_weak_path(self):
        routes = RouteTable(mode="reliable")
        self.assertTrue(routes.update(9, 5, advertised_hops=1, link_rssi=-105, link_snr=7, now_s=1))
        self.assertTrue(routes.update(9, 3, advertised_hops=2, link_rssi=-76, link_snr=13, now_s=2))
        self.assertEqual(routes.next_hop(9), 3)

    def test_fastest_keeps_shorter_path_even_when_weaker(self):
        routes = RouteTable(mode="fastest")
        self.assertTrue(routes.update(9, 5, advertised_hops=1, link_rssi=-105, link_snr=7, now_s=1))
        self.assertFalse(routes.update(9, 3, advertised_hops=2, link_rssi=-76, link_snr=13, now_s=2))
        self.assertEqual(routes.next_hop(9), 5)


class MeshNetworkTests(unittest.TestCase):
    def test_first_tick_advertises_hello_and_route_immediately(self):
        radio = FakeRadio()
        mesh = MeshNetwork(1, radio)
        mesh.tick()
        sent_payloads = [pkt for pkt, _ in radio.sent]
        self.assertTrue(any(pkt.startswith(b"H:1") for pkt in sent_payloads))
        self.assertTrue(any(pkt.startswith(b"R:1:1:") for pkt in sent_payloads))

    def test_no_dtn_for_control_payload_without_route(self):
        radio = FakeRadio()
        mesh = MeshNetwork(1, radio)
        self.assertFalse(mesh.send_data(9, "CMD:1:FORWARD:50"))
        self.assertEqual(len(mesh.dtn), 0)

    def test_dtn_for_non_control_payload_without_route(self):
        radio = FakeRadio()
        mesh = MeshNetwork(1, radio)
        self.assertFalse(mesh.send_data(9, "hello"))
        self.assertEqual(len(mesh.dtn), 1)

    def test_route_packet_updates_table_and_rebroadcasts(self):
        radio = FakeRadio()
        sink = FakeSink()
        mesh = MeshNetwork(1, radio, event_sink=sink)
        radio.inbox.append(b"R:5:2:7:0")
        mesh.poll_radio()
        self.assertEqual(mesh.routes.next_hop(5), 2)
        self.assertTrue(any(event.startswith("MESH_ROUTE:5|2|1") for event in sink.events))
        self.assertTrue(any(pkt.startswith(b"R:5:1:7:1") for pkt, _ in radio.sent))

    def test_local_delivery_reaches_endpoint(self):
        radio = FakeRadio()
        endpoint = FakeEndpoint()
        mesh = MeshNetwork(2, radio, endpoint=endpoint)
        radio.inbox.append(b"D:1:2:2:9:4:hello")
        mesh.poll_radio()
        self.assertEqual(endpoint.delivered, [(1, 2, "hello")])

    def test_broadcast_control_is_dropped(self):
        radio = FakeRadio()
        endpoint = FakeEndpoint()
        sink = FakeSink()
        mesh = MeshNetwork(2, radio, endpoint=endpoint, event_sink=sink)
        radio.inbox.append(b"D:1:0:0:9:4:CMD:9:FORWARD:50")
        mesh.poll_radio()
        self.assertEqual(endpoint.delivered, [])
        self.assertEqual(radio.sent, [])
        self.assertTrue(any(event.startswith("MESH_DROP:BROADCAST_CONTROL") for event in sink.events))

    def test_overheard_unicast_does_not_poison_dedup_cache(self):
        radio = FakeRadio()
        mesh = MeshNetwork(3, radio)
        mesh.routes.update(9, 4, advertised_hops=0, link_rssi=-70, now_s=1)

        radio.inbox.append(b"D:1:9:2:7:4:hello")
        mesh.poll_radio()
        self.assertEqual(radio.sent, [])

        radio.inbox.append(b"D:1:9:3:7:4:hello")
        mesh.poll_radio()
        self.assertTrue(any(pkt.startswith(b"D:1:9:4:7:3:hello") for pkt, _ in radio.sent))

    def test_dtn_packet_is_kept_when_retry_send_fails(self):
        radio = FakeRadio(send_ok=False)
        mesh = MeshNetwork(1, radio)
        self.assertFalse(mesh.send_data(9, "hello"))
        self.assertEqual(len(mesh.dtn), 1)
        now = time.monotonic()
        mesh.routes.update(9, 2, advertised_hops=0, link_rssi=-70, now_s=now)
        mesh.dtn.wake(9, now)
        mesh._last_hello = now
        mesh._last_route = now
        mesh._last_expire = now
        mesh.tick()
        self.assertEqual(len(mesh.dtn), 1)


class RadioAdapterTests(unittest.TestCase):
    def test_async_poll_restarts_rx_after_packet(self):
        radio = FakeAsyncRadio((b"H:1", 0))
        adapter = RadioAdapter(FakeHardware(radio))
        self.assertEqual(adapter.poll(), b"H:1")
        self.assertEqual(radio.recv_starts, 1)

    def test_async_poll_restarts_rx_after_crc_error(self):
        radio = FakeAsyncRadio((None, 1))
        adapter = RadioAdapter(FakeHardware(radio))
        self.assertIsNone(adapter.poll())
        self.assertEqual(radio.recv_starts, 1)


class GadgetEndpointTests(unittest.TestCase):
    def test_endpoint_reports_capabilities(self):
        radio = FakeRadio()
        endpoint = GadgetEndpoint(capabilities={"servo": FakeServo()})
        mesh = MeshNetwork(2, radio, endpoint=endpoint)
        mesh.routes.update(1, 1, advertised_hops=0, link_rssi=-70, now_s=1)
        radio.inbox.append(b"D:1:2:2:9:4:CAPS?")
        mesh.poll_radio()
        self.assertTrue(any(pkt.endswith(b"CAPS:2:servo") for pkt, _ in radio.sent))

    def test_endpoint_servo_command_uses_injected_capability(self):
        radio = FakeRadio()
        servo = FakeServo()
        endpoint = GadgetEndpoint(capabilities={"servo": servo})
        mesh = MeshNetwork(2, radio, endpoint=endpoint)
        mesh.routes.update(1, 1, advertised_hops=0, link_rssi=-70, now_s=1)
        radio.inbox.append(b"D:1:2:2:9:4:SERVO:90")
        mesh.poll_radio()
        self.assertEqual(servo.angles, [90.0])
        self.assertTrue(any(pkt.endswith(b"ACK:SERVO:90.0") for pkt, _ in radio.sent))

    def test_endpoint_servo_command_without_capability_returns_error(self):
        radio = FakeRadio()
        endpoint = GadgetEndpoint()
        mesh = MeshNetwork(2, radio, endpoint=endpoint)
        mesh.routes.update(1, 1, advertised_hops=0, link_rssi=-70, now_s=1)
        radio.inbox.append(b"D:1:2:2:9:4:SERVO:90")
        mesh.poll_radio()
        self.assertTrue(any(pkt.endswith(b"ERROR:SERVO:NO_CAPABILITY") for pkt, _ in radio.sent))

    def test_endpoint_debug_can_be_enabled_over_mesh(self):
        radio = FakeRadio()
        endpoint = GadgetEndpoint()
        mesh = MeshNetwork(2, radio, endpoint=endpoint)
        mesh.routes.update(1, 1, advertised_hops=0, link_rssi=-70, now_s=1)
        radio.inbox.append(b"D:1:2:2:9:4:ENDPOINT:DEBUG:ON:1")
        mesh.poll_radio()
        self.assertTrue(endpoint.debug_enabled)
        self.assertEqual(endpoint.debug_target, 1)
        self.assertTrue(any(pkt.endswith(b"ACK:DEBUG:ON:1") for pkt, _ in radio.sent))

    def test_endpoint_control_command_returns_ack(self):
        radio = FakeRadio()
        endpoint = GadgetEndpoint()
        mesh = MeshNetwork(2, radio, endpoint=endpoint)
        mesh.routes.update(1, 1, advertised_hops=0, link_rssi=-70, now_s=1)
        radio.inbox.append(b"D:1:2:2:9:4:H:135.0")
        mesh.poll_radio()
        self.assertTrue(any(pkt.endswith(b"ACK:CTRL:H:135.0") for pkt, _ in radio.sent))

    def test_endpoint_debug_tick_sends_periodic_packet(self):
        radio = FakeRadio()
        endpoint = GadgetEndpoint()
        mesh = MeshNetwork(2, radio, endpoint=endpoint)
        mesh.routes.update(1, 1, advertised_hops=0, link_rssi=-70, now_s=1)
        endpoint.debug_enabled = True
        endpoint.debug_target = 1
        endpoint._last_debug_s = time.monotonic() - 20
        endpoint.tick(mesh)
        self.assertTrue(any(pkt.startswith(b"D:2:1:1:") and b":P" in pkt for pkt, _ in radio.sent))

    def test_endpoint_debug_can_be_enabled_locally(self):
        radio = FakeRadio()
        endpoint = GadgetEndpoint()
        mesh = MeshNetwork(2, radio, endpoint=endpoint)
        self.assertTrue(endpoint.on_local_command("DEBUG:ON:1", mesh))
        self.assertTrue(endpoint.debug_enabled)
        self.assertEqual(endpoint.debug_target, 1)


if __name__ == "__main__":
    unittest.main()
