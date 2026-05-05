# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Small logger utility for Prompt 1 scaffold."""


class _Logger:
    def __init__(self, name):
        self.name = name

    def _emit(self, level, message, *args):
        if args:
            message = message % args
        print("[{0}] {1}: {2}".format(level, self.name, message))

    def info(self, message, *args):
        self._emit("INFO", message, *args)

    def warn(self, message, *args):
        self._emit("WARN", message, *args)

    def error(self, message, *args):
        self._emit("ERROR", message, *args)


def get_logger(name):
    return _Logger(name)
