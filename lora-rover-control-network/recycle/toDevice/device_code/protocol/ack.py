# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""ACK tracking with timeout and retry bookkeeping."""


class AckManager:
    def __init__(self):
        self.pending = {}

    def track(self, seq, dst, deadline_ms, packet, attempt=0):
        key = (int(seq), int(dst))
        self.pending[key] = {
            "deadline_ms": int(deadline_ms),
            "packet": packet,
            "attempt": int(attempt),
        }

    def complete(self, seq, src):
        key = (int(seq), int(src))
        return self.pending.pop(key, None) is not None

    def get(self, seq, dst):
        return self.pending.get((int(seq), int(dst)))

    def pop(self, seq, dst):
        return self.pending.pop((int(seq), int(dst)), None)

    def expired(self, now_ms):
        now_ms = int(now_ms)
        out = []
        for key, value in list(self.pending.items()):
            if now_ms >= value["deadline_ms"]:
                out.append((key, value))
        return out
