# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Fixed-capacity neighbor table with smoothing and sliding windows."""

from config import LORA_MAX_SF, LORA_MIN_SF, MAX_NEIGHBORS
from support.ringbuffer import RingBuffer
from support.timebase import ticks_ms


DEFAULT_ALPHA = 0.2
DEFAULT_WINDOW = 20


def _exp_smooth(previous, sample, alpha):
    if previous is None:
        return float(sample)
    return float(alpha) * float(sample) + (1.0 - float(alpha)) * float(previous)


class NeighborEntry:
    __slots__ = (
        "node_id",
        "role",
        "hop_level",
        "avg_rssi_dbm",
        "avg_snr_db",
        "pdr",
        "retry_rate",
        "current_sf",
        "min_sf",
        "max_sf",
        "est_airtime_ms",
        "queue_delay_ms",
        "parent_id",
        "child_count",
        "battery_v",
        "last_seen_ms",
        "last_sf_change_ms",
        "quality_score",
        "_alpha",
        "_tx_window",
        "_retry_window",
    )

    def __init__(self, node_id, alpha=DEFAULT_ALPHA, window_size=DEFAULT_WINDOW):
        self.node_id = int(node_id)
        self.role = 0
        self.hop_level = 0
        self.avg_rssi_dbm = None
        self.avg_snr_db = None
        self.pdr = 0.0
        self.retry_rate = 0.0
        self.current_sf = 9
        self.min_sf = LORA_MIN_SF
        self.max_sf = LORA_MAX_SF
        self.est_airtime_ms = 0.0
        self.queue_delay_ms = 0.0
        self.parent_id = 0
        self.child_count = 0
        self.battery_v = 0.0
        self.last_seen_ms = 0
        self.last_sf_change_ms = 0
        self.quality_score = 0.0

        self._alpha = float(alpha)
        self._tx_window = RingBuffer(window_size)
        self._retry_window = RingBuffer(window_size)

    def touch(self, now_ms=None):
        self.last_seen_ms = int(ticks_ms() if now_ms is None else now_ms)

    def update_signal(self, rssi_dbm=None, snr_db=None, now_ms=None):
        if rssi_dbm is not None:
            self.avg_rssi_dbm = _exp_smooth(self.avg_rssi_dbm, rssi_dbm, self._alpha)
        if snr_db is not None:
            self.avg_snr_db = _exp_smooth(self.avg_snr_db, snr_db, self._alpha)
        self.touch(now_ms)

    def update_latency(self, airtime_ms=None, queue_delay_ms=None):
        if airtime_ms is not None:
            self.est_airtime_ms = _exp_smooth(self.est_airtime_ms, airtime_ms, self._alpha)
        if queue_delay_ms is not None:
            self.queue_delay_ms = _exp_smooth(self.queue_delay_ms, queue_delay_ms, self._alpha)

    def record_tx(self, delivered, retries=0, now_ms=None):
        self._tx_window.append(1 if delivered else 0)
        self._retry_window.append(max(0, int(retries)))
        self.touch(now_ms)
        self._refresh_delivery_metrics()

    def _refresh_delivery_metrics(self):
        tx_values = self._tx_window.items()
        retry_values = self._retry_window.items()
        if tx_values:
            self.pdr = float(sum(tx_values)) / float(len(tx_values))
        if retry_values:
            retries = 0
            tx_count = len(retry_values)
            for value in retry_values:
                retries += value
            self.retry_rate = float(retries) / float(tx_count)

    def set_sf(self, sf, now_ms=None):
        sf = int(sf)
        if sf < self.min_sf:
            sf = self.min_sf
        elif sf > self.max_sf:
            sf = self.max_sf
        if sf != self.current_sf:
            self.current_sf = sf
            self.last_sf_change_ms = int(ticks_ms() if now_ms is None else now_ms)


class NeighborTable:
    def __init__(self, capacity=MAX_NEIGHBORS, alpha=DEFAULT_ALPHA, window_size=DEFAULT_WINDOW):
        self.capacity = int(capacity)
        self._alpha = float(alpha)
        self._window_size = int(window_size)
        self._entries = []

    def __len__(self):
        return len(self._entries)

    def find(self, node_id):
        node_id = int(node_id)
        for entry in self._entries:
            if entry.node_id == node_id:
                return entry
        return None

    def remove(self, node_id):
        entry = self.find(node_id)
        if entry is None:
            return False
        self._entries.remove(entry)
        return True

    def _evict_oldest(self):
        if not self._entries:
            return None
        oldest = self._entries[0]
        for entry in self._entries[1:]:
            if entry.last_seen_ms < oldest.last_seen_ms:
                oldest = entry
        self._entries.remove(oldest)
        return oldest

    def get_or_add(self, node_id, allow_evict=True):
        entry = self.find(node_id)
        if entry is not None:
            return entry

        if len(self._entries) >= self.capacity:
            if not allow_evict:
                return None
            self._evict_oldest()

        created = NeighborEntry(node_id, alpha=self._alpha, window_size=self._window_size)
        self._entries.append(created)
        return created

    def prune_stale(self, max_age_ms, now_ms=None):
        now_ms = int(ticks_ms() if now_ms is None else now_ms)
        kept = []
        removed = 0
        for entry in self._entries:
            age = now_ms - int(entry.last_seen_ms)
            if entry.last_seen_ms == 0 or age <= max_age_ms:
                kept.append(entry)
            else:
                removed += 1
        self._entries = kept
        return removed

    def update_link_sample(
        self,
        node_id,
        rssi_dbm=None,
        snr_db=None,
        delivered=None,
        retries=0,
        airtime_ms=None,
        queue_delay_ms=None,
        now_ms=None,
    ):
        entry = self.get_or_add(node_id)
        if entry is None:
            return None

        entry.update_signal(rssi_dbm=rssi_dbm, snr_db=snr_db, now_ms=now_ms)
        entry.update_latency(airtime_ms=airtime_ms, queue_delay_ms=queue_delay_ms)
        if delivered is not None:
            entry.record_tx(bool(delivered), retries=retries, now_ms=now_ms)
        return entry

    def items(self):
        return tuple(self._entries)
