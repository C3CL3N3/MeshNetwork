# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Status LED helper for connection-state indication."""


class StatusLed:
    def __init__(self, logger=None, blink_interval_ms=250):
        self.logger = logger
        self.blink_interval_ms = int(blink_interval_ms)
        self._io = None
        self._active_low = False
        self._state_on = False
        self._last_toggle_ms = 0
        self._last_connected = None
        self._ready = False

    def _log(self, msg, *args):
        if self.logger is not None:
            self.logger.info(msg, *args)

    def _set_output(self, on):
        if self._io is None:
            return
        self._state_on = bool(on)
        self._io.value = (not self._state_on) if self._active_low else self._state_on

    def initialize(self):
        if self._ready:
            return self._io is not None
        self._ready = True
        try:
            import board  # type: ignore
            import digitalio  # type: ignore

            candidates = (
                ("LED_BLUE", True),
                ("LED", False),
                ("D13", False),
            )
            pin = None
            for name, active_low in candidates:
                obj = getattr(board, name, None)
                if obj is not None:
                    pin = obj
                    self._active_low = bool(active_low)
                    break

            if pin is None:
                self._log("Status LED not available")
                return False

            io = digitalio.DigitalInOut(pin)
            io.direction = digitalio.Direction.OUTPUT
            self._io = io
            self._set_output(False)
            return True
        except Exception as exc:
            self._io = None
            self._log("Status LED init failed: %s", exc)
            return False

    def tick(self, now_ms, connected):
        self.initialize()
        if self._io is None:
            return

        connected = bool(connected)
        if connected:
            if self._last_connected is not True:
                self._set_output(True)
            self._last_connected = True
            return

        if self._last_connected is True:
            self._set_output(False)
        self._last_connected = False

        now_ms = int(now_ms)
        if (now_ms - int(self._last_toggle_ms)) >= self.blink_interval_ms:
            self._set_output(not self._state_on)
            self._last_toggle_ms = now_ms