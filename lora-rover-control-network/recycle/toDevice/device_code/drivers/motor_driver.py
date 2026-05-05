# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Motor driver abstraction stub."""


class MotorDriver:
    def __init__(self):
        self.left = 0
        self.right = 0
        self.stopped = True

    def stop(self):
        self.left = 0
        self.right = 0
        self.stopped = True
        return True

    def set_motion(self, throttle_left, throttle_right):
        self.left = int(throttle_left)
        self.right = int(throttle_right)
        self.stopped = self.left == 0 and self.right == 0
        return True
