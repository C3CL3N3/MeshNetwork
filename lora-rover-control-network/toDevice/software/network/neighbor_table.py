# SPDX-License-Identifier: MIT


class NeighborTable:
    def __init__(self, expire_s=120.0):
        self.expire_s = float(expire_s)
        self._items = {}

    def update(self, node_id, rssi=None, snr=None, now_s=0.0):
        node_id = int(node_id)
        previous = self._items.get(node_id, {})
        self._items[node_id] = {
            "rssi": int(rssi) if rssi is not None else previous.get("rssi", -999),
            "snr": float(snr) if snr is not None else previous.get("snr", 0.0),
            "seen": float(now_s),
        }
        return self._items[node_id]

    def get(self, node_id):
        return self._items.get(int(node_id))

    def expire(self, now_s):
        dead = []
        for node_id, item in list(self._items.items()):
            if float(now_s) - item["seen"] > self.expire_s:
                dead.append(node_id)
                del self._items[node_id]
        return dead

    def items(self):
        return self._items.items()

