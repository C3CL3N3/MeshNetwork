# SPDX-License-Identifier: MIT


class DtnQueue:
    """Small store-carry-forward queue for non-control payloads."""

    def __init__(self, max_items=16, ttl_s=30.0, retry_s=3.0):
        self.max_items = int(max_items)
        self.ttl_s = float(ttl_s)
        self.retry_s = float(retry_s)
        self._items = []

    def enqueue(self, packet, now_s):
        if getattr(packet, "ttl", 0) <= 0:
            return False
        key = (packet.src, packet.mid)
        for item in self._items:
            if item["key"] == key:
                return False
        while len(self._items) >= self.max_items:
            self._items.pop(0)
        self._items.append({
            "key": key,
            "packet": packet,
            "born": float(now_s),
            "next_try": float(now_s) + self.retry_s,
        })
        return True

    def wake(self, dst, now_s):
        for item in self._items:
            if item["packet"].dst == int(dst):
                item["next_try"] = float(now_s)

    def pop_ready(self, route_table, now_s):
        ready = []
        keep = []
        for item in self._items:
            packet = item["packet"]
            if float(now_s) - item["born"] > self.ttl_s:
                continue
            if float(now_s) < item["next_try"]:
                keep.append(item)
                continue
            next_hop = route_table.next_hop(packet.dst)
            if next_hop is None:
                item["next_try"] = float(now_s) + self.retry_s
                keep.append(item)
                continue
            packet.next_hop = next_hop
            ready.append(packet)
        self._items = keep
        return ready

    def __len__(self):
        return len(self._items)

