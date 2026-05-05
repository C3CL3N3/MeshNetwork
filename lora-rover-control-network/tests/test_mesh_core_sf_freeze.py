# SPDX-License-Identifier: MIT

import os
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "toDevice"))

import mesh_core


class FakeRadio:
    def __init__(self, send_ok=True):
        self.sf_changes = []
        self.cad_calls = 0
        self.poll_calls = 0
        self.sent = []
        self.inbox = []
        self.send_ok = bool(send_ok)

    def set_sf(self, sf):
        self.sf_changes.append(int(sf))

    def cad(self, timeout_ms=100):
        self.cad_calls += 1
        return False

    def poll(self, timeout_ms=None):
        self.poll_calls += 1
        if self.inbox:
            return self.inbox.pop(0)
        return None

    def send(self, packet_bytes, use_lbt=False):
        self.sent.append((packet_bytes, use_lbt))
        return self.send_ok

    def rssi(self):
        return -70

    def snr(self):
        return 8.0


class MeshCoreSfFreezeTests(unittest.TestCase):
    def setUp(self):
        self.old_cfg = dict(mesh_core._cfg)
        mesh_core._cfg["sf_mode"] = "7"
        mesh_core._cfg["network_sf"] = 7

    def tearDown(self):
        mesh_core._cfg.clear()
        mesh_core._cfg.update(self.old_cfg)

    def test_boot_scan_does_not_sweep_when_sf7_frozen(self):
        radio = FakeRadio()
        mesh = mesh_core.MeshNetwork(2, radio, role="C")

        self.assertFalse(mesh.scan_for_network())

        self.assertEqual(radio.sf_changes, [7])
        self.assertEqual(radio.cad_calls, 0)
        self.assertEqual(radio.poll_calls, 0)
        self.assertEqual(mesh._current_sf, 7)

    def test_auto_sf_config_alone_cannot_enable_sweep(self):
        radio = FakeRadio()
        mesh = mesh_core.MeshNetwork(2, radio, role="C")
        mesh_core._cfg["sf_mode"] = "auto"

        self.assertFalse(mesh.scan_for_network())

        self.assertFalse(mesh_core.SF_AUTO_ENABLED)
        self.assertEqual(radio.sf_changes, [7])
        self.assertEqual(radio.cad_calls, 0)
        self.assertEqual(radio.poll_calls, 0)
        self.assertEqual(mesh._current_sf, 7)

    def test_reconnect_scan_does_not_sweep_or_listen_when_sf7_frozen(self):
        radio = FakeRadio()
        mesh = mesh_core.MeshNetwork(2, radio, role="C")

        self.assertFalse(mesh._reconnect_scan())

        self.assertEqual(radio.sf_changes, [7])
        self.assertEqual(radio.cad_calls, 0)
        self.assertEqual(radio.poll_calls, 0)
        self.assertEqual(mesh._current_sf, 7)

    def test_tick_does_not_reconnect_scan_when_sf7_frozen(self):
        radio = FakeRadio()
        mesh = mesh_core.MeshNetwork(2, radio, role="C")
        mesh._last_neighbor_seen = 0
        mesh._reconnect_scan_at = 0

        with redirect_stdout(StringIO()):
            mesh.tick()

        self.assertEqual(radio.cad_calls, 0)
        self.assertEqual(radio.poll_calls, 0)

    def test_sf_broadcast_is_dropped_not_forwarded_when_sf7_frozen(self):
        radio = FakeRadio()
        mesh = mesh_core.MeshNetwork(2, radio, role="R")
        radio.inbox.append(b"D:1:0:0:9:4:SF:12")

        with redirect_stdout(StringIO()):
            mesh.poll_radio()

        self.assertEqual(radio.sent, [])
        self.assertEqual(mesh._current_sf, 7)

    def test_management_tx_reports_failure(self):
        radio = FakeRadio(send_ok=False)
        mesh = mesh_core.MeshNetwork(2, radio, role="C")

        with redirect_stdout(StringIO()) as out:
            self.assertFalse(mesh.send_hello(role="C"))
            self.assertFalse(mesh.send_route_ad())

        text = out.getvalue()
        self.assertIn("TX_FAIL H N2|C|SF7", text)
        self.assertIn("TX_FAIL R mid=1", text)
        self.assertNotIn("TX_H N2|C|SF7", text)
        self.assertNotIn("TX R mid=1", text)

    def test_quiet_node_wakes_and_reports_when_controller_hello_returns(self):
        mesh_core._cfg['report_topo'] = True
        radio = FakeRadio()
        mesh = mesh_core.MeshNetwork(3, radio, role="R")
        mesh.neighbors.update(2, rssi=-75, snr=13, role="C", now_s=1)
        mesh.routes.update(2, 2, 0, link_rssi=-75, now_s=1)
        with redirect_stdout(StringIO()):
            mesh._set_mode(mesh_core.MODE_QUIET)
        radio.inbox.append(b"H:2:C:7")

        with redirect_stdout(StringIO()):
            mesh.poll_radio()

        self.assertEqual(mesh._mode, mesh_core.MODE_ACTIVE)
        payloads = [packet for packet, _ in radio.sent]
        self.assertTrue(any(b"WELCOME:R" in packet for packet in payloads))
        self.assertTrue(any(b"O:3:2:" in packet for packet in payloads))

        now = __import__("time").monotonic()
        mesh._last_hello = now
        mesh._last_route = now
        mesh._last_topo = now - mesh._topo_interval()
        mesh._last_mgmt_tx = now - mesh_core.MGMT_TX_GAP_S
        with redirect_stdout(StringIO()):
            mesh.tick()

        payloads = [packet for packet, _ in radio.sent]
        self.assertTrue(any(b"T:3:" in packet for packet in payloads))

    def test_quiet_mode_intervals_are_reasonable(self):
        hello_s, route_s, topo_max_s = mesh_core.MODE_INTERVALS[mesh_core.MODE_QUIET]
        # Topology is event-driven; topo_max_s is only the fallback interval
        self.assertLessEqual(hello_s, 60)
        self.assertLessEqual(route_s, 120)
        self.assertLessEqual(topo_max_s, 900)

    def test_expired_neighbor_wakes_active_and_reports_topology(self):
        mesh_core._cfg['report_topo'] = True
        radio = FakeRadio()
        mesh = mesh_core.MeshNetwork(3, radio, role="R")
        mesh.neighbors.update(1, rssi=-70, snr=13, role="E", now_s=1)
        with redirect_stdout(StringIO()):
            mesh._set_mode(mesh_core.MODE_QUIET)
        now = __import__("time").monotonic()
        mesh._last_hello = now
        mesh._last_route = now
        mesh._last_topo = now
        mesh._last_mgmt_tx = now - mesh_core.MGMT_TX_GAP_S

        # Schedule topology via the scheduler (as neighbour-change would)
        mesh._schedule_topology_report(now=now, delay_s=0)
        self.assertTrue(mesh._topo_urgent)

        with redirect_stdout(StringIO()):
            mesh.tick()

        self.assertTrue(any(packet.startswith(b"D:3:0:0:") and b":T:3:" in packet for packet, _ in radio.sent))

    def test_periodic_management_packets_are_staggered(self):
        radio = FakeRadio()
        mesh = mesh_core.MeshNetwork(3, radio, role="R")
        now = __import__("time").monotonic()
        mesh._last_hello = now - 100
        mesh._last_route = now - 100
        mesh._last_topo = now - 100
        mesh._last_expire = now
        mesh._last_mgmt_tx = now - mesh_core.MGMT_TX_GAP_S

        with redirect_stdout(StringIO()):
            mesh.tick()

        self.assertEqual(len(radio.sent), 1)
        self.assertTrue(radio.sent[0][0].startswith(b"H:3:"))

    def test_topology_report_bypasses_lbt_and_logs(self):
        mesh_core._cfg['report_topo'] = True
        radio = FakeRadio()
        mesh = mesh_core.MeshNetwork(3, radio, role="R")
        mesh.neighbors.update(1, rssi=-70, snr=13, role="E", now_s=1)

        out = StringIO()
        with redirect_stdout(out):
            self.assertTrue(mesh.send_topology_report())

        self.assertTrue(any(packet.startswith(b"D:3:0:0:") and b":T:3:" in packet and not use_lbt
                            for packet, use_lbt in radio.sent))
        self.assertIn("TX T seq=1 nbrs=1", out.getvalue())

    def test_send_data_uses_direct_neighbor_when_route_expired(self):
        radio = FakeRadio()
        mesh = mesh_core.MeshNetwork(3, radio, role="R")
        mesh.neighbors.update(1, rssi=-70, snr=13, role="E", now_s=1)

        with redirect_stdout(StringIO()):
            self.assertTrue(mesh.send_data(1, "PING", allow_dtn=False))

        self.assertTrue(any(packet.startswith(b"D:3:1:1:") and packet.endswith(b":PING")
                            for packet, _ in radio.sent))

    def test_forward_uses_direct_neighbor_when_route_expired(self):
        radio = FakeRadio()
        mesh = mesh_core.MeshNetwork(3, radio, role="R")
        mesh.neighbors.update(1, rssi=-70, snr=13, role="E", now_s=1)
        radio.inbox.append(b"D:2:1:3:9:6:ENDPOINT:DEBUG:ON:2")

        out = StringIO()
        with redirect_stdout(out):
            mesh.poll_radio()

        self.assertTrue(any(packet == b"D:2:1:1:9:5:ENDPOINT:DEBUG:ON:2"
                            for packet, _ in radio.sent))
        self.assertIn("FWD D N2", out.getvalue())

    def test_send_data_uses_fresh_topology_when_route_expired(self):
        radio = FakeRadio()
        mesh = mesh_core.MeshNetwork(2, radio, role="C")
        mesh.neighbors.update(5, rssi=-80, snr=9, role="R", now_s=1)
        topo = mesh.codec._decode_topology("T:5:1:1,-95,8.0;2,-80,9.0")
        mesh.topo_tracker.feed(topo, 1)

        out = StringIO()
        with redirect_stdout(out):
            self.assertTrue(mesh.send_data(1, "ENDPOINT:DEBUG:ON:2", allow_dtn=False))

        self.assertTrue(any(packet.startswith(b"D:2:1:5:") and packet.endswith(b":ENDPOINT:DEBUG:ON:2")
                            for packet, _ in radio.sent))
        self.assertIn("TOPO_ROUTE dst=N1 via=N5", out.getvalue())

    def test_route_mode_command_updates_locally_and_broadcasts(self):
        radio = FakeRadio()
        mesh = mesh_core.MeshNetwork(2, radio, role="C")

        with redirect_stdout(StringIO()):
            mesh.set_route_mode("fastest", broadcast=True)

        self.assertEqual(mesh.routes.mode, "fastest")
        self.assertTrue(any(packet.endswith(b":ROUTE_MODE:fastest") for packet, _ in radio.sent))

    def test_reliable_topology_fallback_chooses_stronger_chain(self):
        radio = FakeRadio()
        mesh = mesh_core.MeshNetwork(1, radio, role="C")
        mesh.set_route_mode("reliable")
        mesh.neighbors.update(5, rssi=-105, snr=7, role="R", now_s=1)
        mesh.neighbors.update(3, rssi=-76, snr=13, role="R", now_s=1)
        mesh.topo_tracker.feed(mesh.codec._decode_topology("T:5:1:2,-105,7.0"), 1)
        mesh.topo_tracker.feed(mesh.codec._decode_topology("T:3:1:4,-76,13.0"), 1)
        mesh.topo_tracker.feed(mesh.codec._decode_topology("T:4:1:2,-76,13.0"), 1)

        self.assertEqual(mesh._next_hop_for(2), 3)


if __name__ == "__main__":
    unittest.main()
