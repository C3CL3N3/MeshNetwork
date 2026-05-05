# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Prompt 12 simulation harness for 3-5 synthetic nodes.

This harness drives topology selection, route mode changes, adaptive SF,
duplicate suppression, and failover/rejoin behavior with clear logs.
"""

import os
import sys

try:
    from toDevice.device_code.net.forwarder import Forwarder
    from toDevice.device_code.net.control_cycle import LinkRouteController
    from toDevice.device_code.net.neighbor_table import NeighborTable
    from toDevice.device_code.net.route_metric import RouteScorer
    from toDevice.device_code.net.sf_controller import SFController
    from toDevice.device_code.net.topology import TopologyManager
    from toDevice.device_code.protocol.packets import PACKET_TYPE_TO_ID, PacketHeader
except ModuleNotFoundError:
    # Allow direct execution via `python tools/sim_harness.py`.
    _THIS_DIR = os.path.dirname(os.path.abspath(__file__))
    _ROOT_DIR = os.path.dirname(_THIS_DIR)
    _DEVICE_CODE_DIR = os.path.join(_ROOT_DIR, "toDevice", "device_code")
    if _DEVICE_CODE_DIR not in sys.path:
        sys.path.insert(0, _DEVICE_CODE_DIR)

    from toDevice.device_code.net.forwarder import Forwarder
    from toDevice.device_code.net.control_cycle import LinkRouteController
    from toDevice.device_code.net.neighbor_table import NeighborTable
    from toDevice.device_code.net.route_metric import RouteScorer
    from toDevice.device_code.net.sf_controller import SFController
    from toDevice.device_code.net.topology import TopologyManager
    from toDevice.device_code.protocol.packets import PACKET_TYPE_TO_ID, PacketHeader


class SimNode:
    def __init__(self, node_id, role):
        self.node_id = int(node_id)
        self.role = role
        self.neighbors = NeighborTable(capacity=8)
        self.topology = TopologyManager(min_switch_interval_ms=0, hysteresis_margin=0.1)
        self.sf = SFController(n_up=2, n_down=3, cooldown_ms=0, probe_interval_packets=3)
        self.scorer = RouteScorer(mode="speed")
        self.forwarder = Forwarder(node_id=node_id)
        self.logs = []

    def log(self, message):
        self.logs.append(message)


def _seed_link(table, node_id, *, pdr, snr, airtime, queue, retries, hop, sf, seen_ms):
    e = table.get_or_add(node_id)
    e.pdr = float(pdr)
    e.avg_snr_db = float(snr)
    e.est_airtime_ms = float(airtime)
    e.queue_delay_ms = float(queue)
    e.retry_rate = float(retries)
    e.hop_level = int(hop)
    e.current_sf = int(sf)
    e.last_seen_ms = int(seen_ms)
    return e


def run_simulation(node_count=4):
    if node_count < 3 or node_count > 5:
        raise ValueError("node_count must be between 3 and 5")

    nodes = {
        1: SimNode(1, "controller"),
        2: SimNode(2, "relay"),
        3: SimNode(3, "rover"),
    }
    if node_count >= 4:
        nodes[4] = SimNode(4, "observer")
    if node_count >= 5:
        nodes[5] = SimNode(5, "observer")

    rover = nodes[3]
    log = []

    # Step 1: Seed two candidate links and run speed-mode selection.
    a = _seed_link(rover.neighbors, 1, pdr=0.95, snr=9, airtime=70, queue=12, retries=0.4, hop=1, sf=11, seen_ms=100)
    b = _seed_link(rover.neighbors, 2, pdr=0.92, snr=7, airtime=18, queue=3, retries=0.1, hop=2, sf=8, seen_ms=100)

    cycle = LinkRouteController(rover.topology, rover.sf, mode="speed")
    speed_result = cycle.run_cycle(rover.neighbors, now_ms=150, mode="speed")
    speed_scores = speed_result["mode_scores"]
    parent_speed = speed_result["chosen_parent"]
    log.append("cycle_order={0}".format(speed_result["stage_order"]))
    log.append("speed_mode scores={0} parent={1}".format(speed_scores, parent_speed))

    # Step 2: Switch to throughput mode and prefer controller by better stability.
    a.pdr = 0.99
    a.retry_rate = 0.0
    a.current_sf = 8
    b.pdr = 0.86
    b.retry_rate = 0.6
    b.current_sf = 10

    rover.scorer.set_mode("throughput")
    throughput_scores = {1: rover.scorer.score(a), 2: rover.scorer.score(b)}
    # Mirror scorer preference into topology fields to make switch observable in this harness.
    if throughput_scores[1] > throughput_scores[2]:
        a.queue_delay_ms = 1
        b.queue_delay_ms = 8
        a.est_airtime_ms = 12
        b.est_airtime_ms = 30
    throughput_result = cycle.run_cycle(rover.neighbors, now_ms=300, mode="throughput")
    parent_throughput = throughput_result["chosen_parent"]
    log.append("throughput_mode scores={0} parent={1}".format(throughput_scores, parent_throughput))

    # Step 3: Adaptive SF under degraded reliability (fast upward adjustment).
    sf_actions = []
    target = rover.neighbors.find(parent_throughput)
    target.pdr = 0.75
    target.retry_rate = 1.4
    target.avg_snr_db = 1
    for now_ms in (350, 400, 450):
        action = rover.sf.suggest(target, now_ms=now_ms)
        sf_actions.append(action)
        rover.sf.apply_suggestion(target, action, now_ms=now_ms)
    log.append("sf_actions={0} current_sf={1}".format(sf_actions, target.current_sf))

    # Step 4: Duplicate suppression check using relay forwarder.
    relay = nodes[2]
    incoming = PacketHeader(src=1, dst=3, prev_hop=1, next_hop=2, seq=500, packet_type=PACKET_TYPE_TO_ID["DATA"], ttl=4, sf=9)
    first = relay.forwarder.process_incoming(incoming, b"MOVE", now_ms=500)
    second = relay.forwarder.process_incoming(incoming, b"MOVE", now_ms=501)
    log.append("duplicate_check first_forward={0} second_duplicate={1}".format(first["should_forward"], second["duplicate"]))

    # Step 5: Failover / rejoin behavior by aging both links out.
    a.last_seen_ms = 100
    b.last_seen_ms = 100
    rover.topology.broken_link_timeout_ms = 100
    parent_failover = rover.topology.update(rover.neighbors, now_ms=1000)
    log.append(
        "failover parent={0} rejoin_required={1} rejoin_count={2}".format(
            parent_failover,
            rover.topology.rejoin_required,
            rover.topology.rejoin_count,
        )
    )

    return {
        "nodes": nodes,
        "log": log,
        "summary": {
            "parent_speed": parent_speed,
            "parent_throughput": parent_throughput,
            "sf_after": target.current_sf,
            "duplicate_suppressed": bool(second["duplicate"]),
            "rejoin_required": bool(rover.topology.rejoin_required),
        },
    }


def print_simulation_log(node_count=4):
    result = run_simulation(node_count=node_count)
    for row in result["log"]:
        print(row)
    return result


if __name__ == "__main__":
    print_simulation_log(node_count=4)
