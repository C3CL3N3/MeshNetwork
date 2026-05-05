# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Topology manager with weighted parent scoring and hysteresis."""

from support.timebase import ticks_ms


DEFAULT_WEIGHTS = {
    "pdr": 4.0,
    "snr": 0.3,
    "airtime": 0.05,
    "queue": 0.1,
    "child": 0.4,
    "hop": 1.0,
}


class TopologyManager:
    def __init__(
        self,
        weights=None,
        hysteresis_margin=0.25,
        min_switch_interval_ms=1000,
        broken_link_timeout_ms=6000,
        min_pdr=0.25,
    ):
        self.weights = dict(DEFAULT_WEIGHTS)
        if weights:
            self.weights.update(weights)

        self.hysteresis_margin = float(hysteresis_margin)
        self.min_switch_interval_ms = int(min_switch_interval_ms)
        self.broken_link_timeout_ms = int(broken_link_timeout_ms)
        self.min_pdr = float(min_pdr)

        self.parent_id = None
        self.parent_score = None
        self.last_switch_ms = 0
        self.rejoin_required = False
        self.rejoin_count = 0

    def score_entry(self, entry):
        """Compute parent score using PDR/SNR and penalty terms."""
        pdr = float(entry.pdr)
        snr = float(entry.avg_snr_db if entry.avg_snr_db is not None else -20.0)
        airtime = float(entry.est_airtime_ms)
        queue = float(entry.queue_delay_ms)
        child = float(entry.child_count)
        hop = float(entry.hop_level)

        score = (
            self.weights["pdr"] * pdr
            + self.weights["snr"] * snr
            - self.weights["airtime"] * airtime
            - self.weights["queue"] * queue
            - self.weights["child"] * child
            - self.weights["hop"] * hop
        )
        entry.quality_score = score
        return score

    def _is_stale(self, entry, now_ms):
        if not entry.last_seen_ms:
            return False
        return (int(now_ms) - int(entry.last_seen_ms)) > self.broken_link_timeout_ms

    def _is_candidate(self, entry, now_ms):
        if self._is_stale(entry, now_ms):
            return False
        if entry.pdr < self.min_pdr:
            return False
        return True

    def _best_candidate(self, neighbor_table, now_ms):
        best_entry = None
        best_score = None
        for entry in neighbor_table.items():
            if not self._is_candidate(entry, now_ms):
                continue
            score = self.score_entry(entry)
            if best_entry is None or score > best_score:
                best_entry = entry
                best_score = score
        return best_entry, best_score

    def _should_switch(self, current_score, best_score, now_ms):
        if current_score is None:
            return True
        if (int(now_ms) - int(self.last_switch_ms)) < self.min_switch_interval_ms:
            return False
        return best_score >= (current_score + self.hysteresis_margin)

    def _mark_rejoin_required(self):
        self.parent_id = None
        self.parent_score = None
        self.rejoin_required = True
        self.rejoin_count += 1

    def _set_parent(self, parent_id, parent_score, now_ms):
        parent_id = int(parent_id)
        changed = self.parent_id != parent_id
        self.parent_id = parent_id
        self.parent_score = float(parent_score)
        if changed:
            self.last_switch_ms = int(now_ms)
        self.rejoin_required = False

    def current_parent_entry(self, neighbor_table):
        if self.parent_id is None:
            return None
        return neighbor_table.find(self.parent_id)

    def is_parent_broken(self, neighbor_table, now_ms=None):
        now_ms = int(ticks_ms() if now_ms is None else now_ms)
        parent = self.current_parent_entry(neighbor_table)
        if parent is None:
            return True
        return not self._is_candidate(parent, now_ms)

    def trigger_rejoin(self):
        self.rejoin_required = True
        self.rejoin_count += 1

    def consume_rejoin_flag(self):
        flag = self.rejoin_required
        self.rejoin_required = False
        return flag

    def update(self, neighbor_table, now_ms=None):
        """Select or maintain a parent based on score, hysteresis, and link health."""
        now_ms = int(ticks_ms() if now_ms is None else now_ms)

        best_entry, best_score = self._best_candidate(neighbor_table, now_ms)
        current_entry = self.current_parent_entry(neighbor_table)

        if current_entry is not None and self._is_candidate(current_entry, now_ms):
            current_score = self.score_entry(current_entry)

            if best_entry is None:
                self._set_parent(current_entry.node_id, current_score, now_ms)
                return self.parent_id

            if best_entry.node_id == current_entry.node_id:
                self._set_parent(current_entry.node_id, current_score, now_ms)
                return self.parent_id

            if self._should_switch(current_score, best_score, now_ms):
                self._set_parent(best_entry.node_id, best_score, now_ms)
                return self.parent_id

            # Hysteresis keeps current parent.
            self._set_parent(current_entry.node_id, current_score, now_ms)
            return self.parent_id

        if best_entry is not None:
            self._set_parent(best_entry.node_id, best_score, now_ms)
            return self.parent_id

        self._mark_rejoin_required()
        return self.parent_id
