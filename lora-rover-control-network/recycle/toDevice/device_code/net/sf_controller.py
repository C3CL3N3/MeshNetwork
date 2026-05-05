# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Link-local adaptive spreading factor controller."""

from config import LORA_MAX_SF, LORA_MIN_SF
from support.timebase import ticks_ms


class SFController:
    def __init__(
        self,
        min_sf=LORA_MIN_SF,
        max_sf=LORA_MAX_SF,
        start_sf=9,
        pdr_down_threshold=0.98,
        pdr_up_threshold=0.90,
        retry_up_threshold=1.0,
        snr_down_threshold=6.0,
        n_up=3,
        n_down=8,
        cooldown_ms=30000,
        probe_interval_packets=30,
    ):
        self.min_sf = int(min_sf)
        self.max_sf = int(max_sf)
        self.start_sf = int(start_sf)

        self.pdr_down_threshold = float(pdr_down_threshold)
        self.pdr_up_threshold = float(pdr_up_threshold)
        self.retry_up_threshold = float(retry_up_threshold)
        self.snr_down_threshold = float(snr_down_threshold)

        self.n_up = int(n_up)
        self.n_down = int(n_down)
        self.cooldown_ms = int(cooldown_ms)
        self.probe_interval_packets = int(probe_interval_packets)

        self._states = {}
        self.last_suggestions = {}

    def _state(self, node_id):
        state = self._states.get(node_id)
        if state is None:
            state = {
                "up_counter": 0,
                "down_counter": 0,
                "last_change_ms": 0,
                "packets_since_probe": 0,
            }
            self._states[node_id] = state
        return state

    def _in_cooldown(self, state, now_ms):
        if state["last_change_ms"] == 0:
            return False
        return (int(now_ms) - int(state["last_change_ms"])) < self.cooldown_ms

    def _clamp_sf(self, sf):
        if sf < self.min_sf:
            return self.min_sf
        if sf > self.max_sf:
            return self.max_sf
        return int(sf)

    def _wants_higher_sf(self, entry):
        return entry.pdr < self.pdr_up_threshold or entry.retry_rate > self.retry_up_threshold

    def _wants_lower_sf(self, entry):
        snr = entry.avg_snr_db if entry.avg_snr_db is not None else -20.0
        return entry.pdr >= self.pdr_down_threshold and snr >= self.snr_down_threshold

    def _track_counters(self, state, entry):
        if self._wants_higher_sf(entry):
            state["up_counter"] += 1
            state["down_counter"] = 0
            return
        if self._wants_lower_sf(entry):
            state["down_counter"] += 1
            state["up_counter"] = 0
            return
        state["up_counter"] = 0
        state["down_counter"] = 0

    def _should_probe_down(self, state, entry):
        if entry.current_sf <= entry.min_sf:
            return False
        if self.probe_interval_packets <= 0:
            return False
        return state["packets_since_probe"] >= self.probe_interval_packets and self._wants_lower_sf(entry)

    def suggest(self, neighbor_entry, now_ms=None):
        """Return adaptive SF action for a single neighbor.

        Returned dict fields:
        - action: "hold" | "set_sf" | "probe"
        - sf: target SF for set_sf/probe, else current
        - reason: decision reason string
        """
        now_ms = int(ticks_ms() if now_ms is None else now_ms)

        if neighbor_entry.current_sf < neighbor_entry.min_sf or neighbor_entry.current_sf > neighbor_entry.max_sf:
            neighbor_entry.current_sf = self._clamp_sf(neighbor_entry.current_sf)

        if neighbor_entry.current_sf == 0:
            neighbor_entry.current_sf = self.start_sf

        state = self._state(neighbor_entry.node_id)
        state["packets_since_probe"] += 1

        self._track_counters(state, neighbor_entry)

        current_sf = int(neighbor_entry.current_sf)
        action = {"action": "hold", "sf": current_sf, "reason": "stable"}

        in_cooldown = self._in_cooldown(state, now_ms)

        if not in_cooldown and state["up_counter"] >= self.n_up and current_sf < neighbor_entry.max_sf:
            next_sf = self._clamp_sf(current_sf + 1)
            state["up_counter"] = 0
            state["down_counter"] = 0
            state["last_change_ms"] = now_ms
            action = {"action": "set_sf", "sf": next_sf, "reason": "reliability_drop"}

        elif not in_cooldown and state["down_counter"] >= self.n_down and current_sf > neighbor_entry.min_sf:
            next_sf = self._clamp_sf(current_sf - 1)
            state["up_counter"] = 0
            state["down_counter"] = 0
            state["last_change_ms"] = now_ms
            action = {"action": "set_sf", "sf": next_sf, "reason": "stable_link"}

        elif self._should_probe_down(state, neighbor_entry):
            probe_sf = self._clamp_sf(current_sf - 1)
            action = {"action": "probe", "sf": probe_sf, "reason": "periodic_probe"}
            state["packets_since_probe"] = 0

        self.last_suggestions[neighbor_entry.node_id] = action
        return action

    def apply_suggestion(self, neighbor_entry, suggestion, now_ms=None):
        """Apply set_sf actions to neighbor entry state."""
        if suggestion is None:
            return False
        if suggestion.get("action") != "set_sf":
            return False
        neighbor_entry.set_sf(int(suggestion["sf"]), now_ms=now_ms)
        return True
