# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Fixed-size ring buffer helper."""


class RingBuffer:
    def __init__(self, capacity):
        self.capacity = int(capacity)
        self._buf = [None] * self.capacity
        self._head = 0
        self._size = 0

    def append(self, value):
        idx = (self._head + self._size) % self.capacity
        self._buf[idx] = value
        if self._size < self.capacity:
            self._size += 1
        else:
            self._head = (self._head + 1) % self.capacity

    def items(self):
        out = []
        for i in range(self._size):
            out.append(self._buf[(self._head + i) % self.capacity])
        return out
