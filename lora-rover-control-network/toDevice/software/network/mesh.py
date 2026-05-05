# SPDX-License-Identifier: MIT

import random
import time

from software import config
from software.network.cache import DedupCache
from software.network.dtn_queue import DtnQueue
from software.network.neighbor_table import NeighborTable
from software.network.route_table import RouteTable
from software.protocol.packets import DataPacket, HelloPacket, PacketCodec, RouteAdPacket


class MeshNetwork:
    def __init__(self, node_id, radio, endpoint=None, event_sink=None):
        self.node_id = int(node_id)
        self.radio = radio
        self.endpoint = endpoint
        self.event_sink = event_sink
        self.codec = PacketCodec()
        self.neighbors = NeighborTable(expire_s=config.NEIGHBOR_EXPIRE_S)
        self.routes = RouteTable(
            expire_s=config.ROUTE_EXPIRE_S,
            switch_margin=config.ROUTE_SWITCH_MARGIN,
            rssi_margin_db=config.ROUTE_RSSI_MARGIN_DB,
            mode=getattr(config, "ROUTE_MODE", "fastest"),
            reliable_hop_penalty_db=getattr(config, "ROUTE_RELIABLE_HOP_PENALTY_DB", 3),
            reliable_switch_margin_db=getattr(config, "ROUTE_RELIABLE_SWITCH_MARGIN_DB", 8),
        )
        self.dtn = DtnQueue(
            max_items=config.DTN_QUEUE_MAX,
            ttl_s=config.DTN_TTL_S,
            retry_s=config.DTN_RETRY_S,
        )
        self.data_cache = DedupCache(config.CACHE_SIZE)
        self.route_cache = DedupCache(config.CACHE_SIZE)
        self.msg_id = 0
        self.route_mid = 0
        now = time.monotonic()
        self._last_hello = now - config.HELLO_INTERVAL_S
        self._last_route = now - config.ROUTE_AD_INTERVAL_S
        self._last_expire = now

    def notify(self, msg):
        if self.event_sink is not None:
            self.event_sink.notify(msg)

    def send_hello(self):
        self.radio.send(self.codec.encode_hello(self.node_id))
        print("TX H N{0}".format(self.node_id))

    def send_route_ad(self):
        self.route_mid = (self.route_mid + 1) & 0xFF
        self.radio.send(self.codec.encode_route_ad(self.node_id, self.node_id, self.route_mid, 0))
        print("TX R mid={0}".format(self.route_mid))

    def set_route_mode(self, mode):
        self.routes.set_mode(mode)
        self.notify("MESH_ROUTE_MODE:{0}".format(self.routes.mode))
        print("ROUTE_MODE:{0}".format(self.routes.mode))

    def send_data(self, dst, payload, allow_dtn=True, use_lbt=True):
        self.msg_id = (self.msg_id + 1) & 0xFF
        self.data_cache.mark((self.node_id, self.msg_id))
        next_hop = 0 if int(dst) == 0 else self.routes.next_hop(dst)
        packet = DataPacket(self.node_id, int(dst), next_hop or 0, self.msg_id, config.TTL_DEFAULT, payload)
        if int(dst) != 0 and next_hop is None:
            if allow_dtn and not self._is_control_payload(payload):
                self.dtn.enqueue(packet, time.monotonic())
                self.notify("MESH_ERR:NO_ROUTE:{0}".format(dst))
                print("DTN queue local dst=N{0} mid={1}".format(dst, self.msg_id))
            else:
                self.notify("MESH_ERR:NO_ROUTE:{0}".format(dst))
                print("drop no route dst=N{0}".format(dst))
            return False
        ok = self.radio.send(
            self.codec.encode_data(packet.src, packet.dst, packet.next_hop, packet.mid, packet.ttl, packet.payload),
            use_lbt=use_lbt,
        )
        if ok:
            self.notify("MESH_TX:{0}|{1}|{2}|{3}|{4}|{5}".format(
                packet.src, packet.dst, packet.next_hop, packet.mid, packet.ttl, packet.payload
            ))
            print("TX D dst=N{0} nh=N{1} mid={2} '{3}'".format(
                packet.dst, packet.next_hop, packet.mid, packet.payload
            ))
        return ok

    def tick(self):
        now = time.monotonic()
        if now - self._last_hello >= config.HELLO_INTERVAL_S:
            self._last_hello = now
            self.send_hello()
        if now - self._last_route >= config.ROUTE_AD_INTERVAL_S:
            self._last_route = now
            self.send_route_ad()
        if now - self._last_expire >= config.EXPIRE_INTERVAL_S:
            self._last_expire = now
            dead_neighbors = self.neighbors.expire(now)
            dead_routes = self.routes.expire(now, dead_neighbors=dead_neighbors)
            if dead_neighbors:
                print("expired nb: {0}".format(dead_neighbors))
            if dead_routes:
                print("expired rt: {0}".format(dead_routes))
        for packet in self.dtn.pop_ready(self.routes, now):
            encoded = self.codec.encode_data(packet.src, packet.dst, packet.next_hop, packet.mid, packet.ttl, packet.payload)
            print("DTN deliver src=N{0} dst=N{1} nh=N{2} mid={3}".format(
                packet.src, packet.dst, packet.next_hop, packet.mid
            ))
            if not self.radio.send(encoded, use_lbt=True):
                self.dtn.enqueue(packet, now)

    def poll_radio(self):
        raw = self.radio.poll()
        if raw is None:
            return
        try:
            packet = self.codec.decode(raw)
        except Exception as exc:
            print("decode err: {0}".format(exc))
            return
        if isinstance(packet, HelloPacket):
            self._on_hello(packet)
        elif isinstance(packet, RouteAdPacket):
            self._on_route(packet)
        elif isinstance(packet, DataPacket):
            self._on_data(packet)

    def _on_hello(self, packet):
        if packet.src == self.node_id:
            return
        rssi = self.radio.rssi()
        snr = self.radio.snr()
        self.neighbors.update(packet.src, rssi=rssi, snr=snr, now_s=time.monotonic())
        self.notify("MESH_NB:{0}|{1}|{2:.1f}".format(packet.src, rssi, snr))
        print("RX H src=N{0} rssi={1} snr={2:.1f}".format(packet.src, rssi, snr))

    def _on_route(self, packet):
        if packet.orig == self.node_id or self.route_cache.seen((packet.orig, packet.mid)):
            return
        self.route_cache.mark((packet.orig, packet.mid))
        rssi = self.radio.rssi()
        snr = self.radio.snr()
        self.neighbors.update(packet.fwd, rssi=rssi, snr=snr, now_s=time.monotonic())
        improved = self.routes.update(packet.orig, packet.fwd, packet.hops,
                                      link_rssi=rssi, link_snr=snr,
                                      path_rssi=packet.path_rssi, path_snr=packet.path_snr,
                                      now_s=time.monotonic())
        route = self.routes.get(packet.orig) or {}
        print("RX R orig=N{0} fwd=N{1} mid={2} hops={3} -> nh=N{4} total={5} {6}".format(
            packet.orig,
            packet.fwd,
            packet.mid,
            packet.hops,
            route.get("next_hop", "?"),
            route.get("hops", "?"),
            "[NEW]" if improved else "[known]",
        ))
        if improved:
            self.dtn.wake(packet.orig, time.monotonic())
            self.notify("MESH_ROUTE:{0}|{1}|{2}".format(packet.orig, route["next_hop"], route["hops"]))
        if packet.hops + 1 < config.ROUTE_TTL:
            route = self.routes.get(packet.orig) or {}
            time.sleep(random.uniform(config.ROUTE_JITTER_MIN_S, config.ROUTE_JITTER_MAX_S))
            self.radio.send(
                self.codec.encode_route_ad(packet.orig, self.node_id, packet.mid, packet.hops + 1,
                                           route.get("path_rssi"), route.get("path_snr")),
                use_lbt=True,
            )

    def _on_data(self, packet):
        if packet.src == self.node_id:
            return
        is_broadcast = packet.dst == 0 or packet.next_hop == 0
        is_for_me = packet.dst == self.node_id or packet.next_hop == self.node_id
        if not is_broadcast and not is_for_me:
            return
        if self.data_cache.seen((packet.src, packet.mid)):
            return
        self.data_cache.mark((packet.src, packet.mid))
        rssi = self.radio.rssi()
        snr = self.radio.snr()
        print("RX D src=N{0} dst=N{1} nh=N{2} mid={3} ttl={4} rssi={5} '{6}'".format(
            packet.src, packet.dst, packet.next_hop, packet.mid, packet.ttl, rssi, packet.payload
        ))
        if packet.dst == 0 or packet.dst == self.node_id:
            if packet.dst == 0 and self._is_control_payload(packet.payload):
                self.notify("MESH_DROP:BROADCAST_CONTROL:{0}:{1}".format(packet.src, packet.mid))
                print("drop broadcast control src=N{0} mid={1}".format(packet.src, packet.mid))
                return
            self.notify("MESH_RX:{0}|{1}|{2}|{3}|{4}|{5:.1f}|{6}".format(
                packet.src, packet.dst, packet.mid, packet.ttl, rssi, snr, packet.payload
            ))
            if self.endpoint is not None:
                self.endpoint.on_data(packet, self)
        if packet.dst == self.node_id or packet.ttl <= 1:
            return
        if packet.next_hop == 0:
            if random.random() > self._relay_probability(rssi):
                return
            time.sleep(random.uniform(config.RELAY_JITTER_MIN_S, config.RELAY_JITTER_MAX_S))
            self.radio.send(
                self.codec.encode_data(packet.src, packet.dst, 0, packet.mid, packet.ttl - 1, packet.payload),
                use_lbt=True,
            )
            return
        if packet.next_hop != self.node_id:
            return
        next_hop = self.routes.next_hop(packet.dst)
        if next_hop is None:
            if not self._is_control_payload(packet.payload):
                packet.ttl -= 1
                self.dtn.enqueue(packet, time.monotonic())
            return
        time.sleep(random.uniform(config.RELAY_JITTER_MIN_S, config.RELAY_JITTER_MAX_S))
        self.radio.send(
            self.codec.encode_data(packet.src, packet.dst, next_hop, packet.mid, packet.ttl - 1, packet.payload),
            use_lbt=True,
        )

    def _relay_probability(self, rssi):
        if rssi > -60:
            return 0.40
        if rssi > -75:
            return 0.65
        if rssi > -90:
            return 0.85
        return 0.97

    def _is_control_payload(self, payload):
        text = str(payload)
        return text.startswith(config.CONTROL_PREFIXES)
