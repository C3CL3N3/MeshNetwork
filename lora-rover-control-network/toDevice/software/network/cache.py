# SPDX-License-Identifier: MIT


class DedupCache:
    def __init__(self, capacity=60):
        self.capacity = int(capacity)
        self._items = []

    def seen(self, key):
        return key in self._items

    def mark(self, key):
        self._items.append(key)
        while len(self._items) > self.capacity:
            self._items.pop(0)

    def mark_if_new(self, key):
        if self.seen(key):
            return False
        self.mark(key)
        return True

