# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Integrated link-route control cycle orchestration.

Decision order per cycle:
1. Discover neighbors
2. Estimate likely usable SF per link
3. Convert SF to cost (airtime/goodput influence)
4. Choose route
5. Fine-tune SF on chosen link(s)
"""

from net.route_metric import RouteScorer
from support.timebase import ticks_ms


def _estimate_airtime_ms(sf, base_ms=8.0):
    # Simple airtime proxy: doubles per SF step above 7.
    sf = max(7, int(sf))
    return float(base_ms) * float(2 ** (sf - 7))


class LinkRouteController:
    def __init__(self, topology_manager, sf_controller, mode="speed", stale_prune_ms=None):
        self.topology = topology_manager
        self.sf_controller = sf_controller
        self.route_scorer = RouteScorer(mode=mode)
        self.stale_prune_ms = stale_prune_ms

    def set_mode(self, mode):
        self.route_scorer.set_mode(mode)

    def run_cycle(self, neighbor_table, now_ms=None, mode=None):
        now_ms = int(ticks_ms() if now_ms is None else now_ms)
        if mode is not None:
            self.set_mode(mode)

        logs = []
        stage_order = []

        # 1) Discover neighbors
        stage_order.append("discover_neighbors")
        if self.stale_prune_ms is not None:
            removed = neighbor_table.prune_stale(self.stale_prune_ms, now_ms=now_ms)
            logs.append("discover pruned={0}".format(removed))
        entries = list(neighbor_table.items())
        discovered_ids = [e.node_id for e in entries]
        logs.append("discover neighbors={0}".format(discovered_ids))

        # 2) Estimate likely usable SF per link
        stage_order.append("estimate_link_sf")
        sf_suggestions = {}
        predicted_sf = {}
        for entry in entries:
            action = self.sf_controller.suggest(entry, now_ms=now_ms)
            sf_suggestions[entry.node_id] = action
            if action["action"] in ("set_sf", "probe"):
                predicted_sf[entry.node_id] = int(action["sf"])
            else:
                predicted_sf[entry.node_id] = int(entry.current_sf)
        logs.append("sf suggestions={0}".format(sf_suggestions))

        # 3) Convert SF into cost influence
        stage_order.append("convert_sf_to_cost")
        originals = {}
        predicted_costs = {}
        mode_scores = {}
        for entry in entries:
            originals[entry.node_id] = {
                "current_sf": int(entry.current_sf),
                "est_airtime_ms": float(entry.est_airtime_ms),
            }

            p_sf = predicted_sf[entry.node_id]
            p_airtime = _estimate_airtime_ms(p_sf)
            predicted_costs[entry.node_id] = {
                "predicted_sf": p_sf,
                "predicted_airtime_ms": p_airtime,
            }

            # Apply temporary predicted values for ranking.
            entry.current_sf = p_sf
            entry.est_airtime_ms = p_airtime
            mode_scores[entry.node_id] = self.route_scorer.score(entry)
        logs.append("cost predicted={0}".format(predicted_costs))

        # 4) Choose route
        stage_order.append("choose_route")
        chosen_parent = self.topology.update(neighbor_table, now_ms=now_ms)
        logs.append("route chosen_parent={0}".format(chosen_parent))

        # 5) Fine-tune SF on chosen link(s)
        stage_order.append("fine_tune_selected_links")
        sf_applied = False
        applied_action = None
        if chosen_parent is not None:
            chosen_entry = neighbor_table.find(chosen_parent)
            action = sf_suggestions.get(chosen_parent)
            if chosen_entry is not None and action is not None:
                sf_applied = self.sf_controller.apply_suggestion(chosen_entry, action, now_ms=now_ms)
                if sf_applied:
                    # Keep chosen link airtime aligned with applied SF.
                    chosen_entry.est_airtime_ms = _estimate_airtime_ms(chosen_entry.current_sf)
                    applied_action = action

        # Restore non-chosen links to pre-estimation values.
        for entry in entries:
            if chosen_parent is not None and entry.node_id == chosen_parent and sf_applied:
                continue
            entry.current_sf = originals[entry.node_id]["current_sf"]
            entry.est_airtime_ms = originals[entry.node_id]["est_airtime_ms"]

        logs.append("sf applied={0} action={1}".format(sf_applied, applied_action))

        return {
            "stage_order": stage_order,
            "discovered_ids": discovered_ids,
            "sf_suggestions": sf_suggestions,
            "predicted_costs": predicted_costs,
            "mode_scores": mode_scores,
            "chosen_parent": chosen_parent,
            "sf_applied": sf_applied,
            "applied_action": applied_action,
            "logs": logs,
        }
