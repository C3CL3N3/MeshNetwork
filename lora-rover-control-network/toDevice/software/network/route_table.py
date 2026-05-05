# SPDX-License-Identifier: MIT


class RouteTable:
    """Distance-vector route table with selectable route policy.

    ``fastest`` keeps the old behavior: lower hop count wins, RSSI only breaks
    ties. ``reliable`` scores the path bottleneck RSSI/SNR and tolerates a few
    extra hops when the shorter path is weak.
    """

    MODE_FASTEST = "fastest"
    MODE_RELIABLE = "reliable"

    def __init__(
        self,
        expire_s=90.0,
        switch_margin=0,
        rssi_margin_db=4,
        mode="fastest",
        reliable_hop_penalty_db=3,
        reliable_switch_margin_db=8,
    ):
        self.expire_s = float(expire_s)
        self.switch_margin = int(switch_margin)
        self.rssi_margin_db = int(rssi_margin_db)
        self.mode = self._normalize_mode(mode)
        self.reliable_hop_penalty_db = int(reliable_hop_penalty_db)
        self.reliable_switch_margin_db = int(reliable_switch_margin_db)
        self._items = {}

    def _normalize_mode(self, mode):
        mode = str(mode or self.MODE_FASTEST).strip().lower()
        if mode not in (self.MODE_FASTEST, self.MODE_RELIABLE):
            return self.MODE_FASTEST
        return mode

    def set_mode(self, mode):
        self.mode = self._normalize_mode(mode)

    def _path_rssi(self, link_rssi, advertised_path_rssi):
        link = int(link_rssi) if link_rssi is not None else -999
        path = int(advertised_path_rssi) if advertised_path_rssi is not None else link
        if path <= -999:
            return link
        if link <= -999:
            return path
        return min(link, path)

    def _path_snr(self, link_snr, advertised_path_snr):
        link = float(link_snr) if link_snr is not None else None
        path = float(advertised_path_snr) if advertised_path_snr is not None else link
        if link is None:
            return path if path is not None else 0.0
        if path is None:
            return link
        return min(link, path)

    def _reliable_score(self, hops, path_rssi, path_snr):
        snr_bonus = max(-20.0, min(20.0, float(path_snr))) * 2.0
        hop_penalty = max(0, int(hops) - 1) * self.reliable_hop_penalty_db
        return float(path_rssi) + snr_bonus - hop_penalty

    def update(
        self,
        dest,
        next_hop,
        advertised_hops,
        link_rssi=None,
        link_snr=None,
        path_rssi=None,
        path_snr=None,
        now_s=0.0,
    ):
        dest = int(dest)
        next_hop = int(next_hop)
        total_hops = int(advertised_hops) + 1
        rssi = int(link_rssi) if link_rssi is not None else -999
        snr = float(link_snr) if link_snr is not None else 0.0
        bottleneck_rssi = self._path_rssi(link_rssi, path_rssi)
        bottleneck_snr = self._path_snr(link_snr, path_snr)
        score = self._reliable_score(total_hops, bottleneck_rssi, bottleneck_snr)
        current = self._items.get(dest)

        improved = False
        if current is None:
            improved = True
        elif self.mode == self.MODE_RELIABLE:
            if score >= current.get("score", -9999) + self.reliable_switch_margin_db:
                improved = True
            elif total_hops < current["hops"] and score >= current.get("score", -9999) - self.reliable_switch_margin_db:
                improved = True
        else:
            if total_hops < current["hops"] - self.switch_margin:
                improved = True
            elif total_hops == current["hops"] and bottleneck_rssi >= current["path_rssi"] + self.rssi_margin_db:
                improved = True

        if improved:
            self._items[dest] = {
                "next_hop": next_hop,
                "hops": total_hops,
                "link_rssi": rssi,
                "link_snr": snr,
                "path_rssi": bottleneck_rssi,
                "path_snr": bottleneck_snr,
                "score": score,
                "seen": float(now_s),
            }
            return True

        if current is not None and current["next_hop"] == next_hop:
            current["seen"] = float(now_s)
            current["link_rssi"] = rssi
            current["link_snr"] = snr
            current["path_rssi"] = bottleneck_rssi
            current["path_snr"] = bottleneck_snr
            current["score"] = score
        return False

    def next_hop(self, dest):
        route = self._items.get(int(dest))
        return route["next_hop"] if route else None

    def get(self, dest):
        return self._items.get(int(dest))

    def expire(self, now_s, dead_neighbors=None):
        dead_neighbors = set(dead_neighbors or [])
        dead_routes = []
        for dest, route in list(self._items.items()):
            stale = float(now_s) - route["seen"] > self.expire_s
            broken_next_hop = route["next_hop"] in dead_neighbors
            if stale or broken_next_hop:
                dead_routes.append(dest)
                del self._items[dest]
        return dead_routes

    def items(self):
        return self._items.items()

    def __len__(self):
        return len(self._items)
