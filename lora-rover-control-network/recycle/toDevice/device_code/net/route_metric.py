# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Route scoring profiles for speed and throughput modes."""

from config import VALID_MODES


SPEED_WEIGHTS = {
    "pdr": 4.0,
    "snr": 0.25,
    "airtime": 0.07,
    "queue": 0.12,
    "retries": 0.7,
    "hop": 1.2,
}

THROUGHPUT_WEIGHTS = {
    "goodput": 2.0,
    "pdr": 2.0,
    "loss": 1.0,
    "jitter": 0.08,
    "energy": 0.05,
    "hop": 0.6,
}


def _as_float(value, fallback=0.0):
    if value is None:
        return float(fallback)
    return float(value)


def estimate_bottleneck_goodput(entry):
    """Simple relative goodput estimate for route ranking.

    The estimator intentionally stays lightweight for embedded usage.
    """
    sf = _as_float(getattr(entry, "current_sf", 9), 9.0)
    pdr = _as_float(getattr(entry, "pdr", 0.0), 0.0)
    retries = _as_float(getattr(entry, "retry_rate", 0.0), 0.0)

    # Relative PHY proxy: lower SF means higher nominal symbol throughput.
    phy_factor = 1.0 / max(1.0, sf - 6.0)
    retry_penalty = 1.0 / (1.0 + max(0.0, retries))
    return max(0.0, phy_factor * pdr * retry_penalty)


def score_speed(entry, weights=None):
    """Speed mode: prefer low delay with acceptable reliability."""
    w = dict(SPEED_WEIGHTS)
    if weights:
        w.update(weights)

    pdr = _as_float(getattr(entry, "pdr", 0.0))
    snr = _as_float(getattr(entry, "avg_snr_db", -20.0), -20.0)
    airtime = _as_float(getattr(entry, "est_airtime_ms", 0.0))
    queue = _as_float(getattr(entry, "queue_delay_ms", 0.0))
    retries = _as_float(getattr(entry, "retry_rate", 0.0))
    hop = _as_float(getattr(entry, "hop_level", 0.0))

    return (
        w["pdr"] * pdr
        + w["snr"] * snr
        - w["airtime"] * airtime
        - w["queue"] * queue
        - w["retries"] * retries
        - w["hop"] * hop
    )


def score_throughput(entry, weights=None):
    """Throughput mode: prefer stable link goodput."""
    w = dict(THROUGHPUT_WEIGHTS)
    if weights:
        w.update(weights)

    goodput = estimate_bottleneck_goodput(entry)
    pdr = _as_float(getattr(entry, "pdr", 0.0))
    loss = max(0.0, 1.0 - pdr)
    # Reuse queue delay as a lightweight jitter proxy.
    jitter = _as_float(getattr(entry, "queue_delay_ms", 0.0))
    sf = _as_float(getattr(entry, "current_sf", 9.0), 9.0)
    retries = _as_float(getattr(entry, "retry_rate", 0.0))
    hop = _as_float(getattr(entry, "hop_level", 0.0))

    energy_cost = sf + retries
    return (
        w["goodput"] * goodput
        + w["pdr"] * pdr
        - w["loss"] * loss
        - w["jitter"] * jitter
        - w["energy"] * energy_cost
        - w["hop"] * hop
    )


def score_entry(entry, mode="speed", weights=None):
    mode = (mode or "speed").lower()
    if mode not in VALID_MODES:
        raise ValueError("invalid mode: {0}".format(mode))
    if mode == "throughput":
        return score_throughput(entry, weights=weights)
    return score_speed(entry, weights=weights)


class RouteScorer:
    """Runtime mode-switchable scorer utility."""

    def __init__(self, mode="speed"):
        mode = mode.lower()
        if mode not in VALID_MODES:
            raise ValueError("invalid mode: {0}".format(mode))
        self.mode = mode

    def set_mode(self, mode):
        mode = mode.lower()
        if mode not in VALID_MODES:
            raise ValueError("invalid mode: {0}".format(mode))
        self.mode = mode

    def score(self, entry, weights=None):
        return score_entry(entry, mode=self.mode, weights=weights)
