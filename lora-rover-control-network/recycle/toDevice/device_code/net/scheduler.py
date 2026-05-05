# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Lightweight transmission scheduler with ACK gap and backoff."""

import random

from config import ACK_GAP_MS, BACKOFF_BASE_MS, BACKOFF_MAX_MS
from support.timebase import ticks_ms


class Scheduler:
    def __init__(
        self,
        ack_gap_ms=ACK_GAP_MS,
        backoff_base_ms=BACKOFF_BASE_MS,
        backoff_max_ms=BACKOFF_MAX_MS,
        #rng_seed=1,
    ):
        self.ack_gap_ms = int(ack_gap_ms)
        self.backoff_base_ms = int(backoff_base_ms)
        self.backoff_max_ms = int(backoff_max_ms)
        #self._rng = random.Random(rng_seed)

    def ack_slot(self, now_ms=None):
        now_ms = int(ticks_ms() if now_ms is None else now_ms)
        return now_ms + self.ack_gap_ms

    def backoff_delay_ms(self, attempt):
        attempt = max(0, int(attempt))
        upper = self.backoff_base_ms * (2 ** attempt)
        upper = min(upper, self.backoff_max_ms)
        if upper <= 0:
            return 0
        return random.randint(0, upper)

    def next_tx_slot(self, attempt=0, now_ms=None):
        now_ms = int(ticks_ms() if now_ms is None else now_ms)
        return now_ms + self.backoff_delay_ms(attempt)
