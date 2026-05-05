# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""ESP32-S3 + SX1262 board mapping (lab-verified pinout)."""

BOARD_NAME = "esp32s3_sx1262"

class _Pin:
	def __init__(self, name):
		self.name = name


try:
	import board  # type: ignore
	import microcontroller  # type: ignore
except Exception:
	class _Board:
		D1 = _Pin("D1")
		D8 = _Pin("D8")
		D9 = _Pin("D9")
		D10 = _Pin("D10")

	class _MicroPins:
		GPIO38 = _Pin("GPIO38")
		GPIO39 = _Pin("GPIO39")
		GPIO40 = _Pin("GPIO40")
		GPIO41 = _Pin("GPIO41")

	class _Micro:
		pin = _MicroPins()

	board = _Board()
	microcontroller = _Micro()

SPI_SCK_PIN = getattr(board, "D8", _Pin("D8"))
SPI_MISO_PIN = getattr(board, "D9", _Pin("D9"))
SPI_MOSI_PIN = getattr(board, "D10", _Pin("D10"))
LORA_RESET_PIN = getattr(board, "D1", _Pin("D1"))
_mp = getattr(microcontroller, "pin", object())
LORA_CS_PIN = getattr(_mp, "GPIO41", _Pin("GPIO41"))
LORA_BUSY_PIN = getattr(_mp, "GPIO40", _Pin("GPIO40"))
LORA_DIO1_PIN = getattr(_mp, "GPIO39", _Pin("GPIO39"))
LORA_RF_SW_PIN = getattr(_mp, "GPIO38", _Pin("GPIO38"))

MOTOR_PWM_LEFT_PIN = 4
MOTOR_PWM_RIGHT_PIN = 5
MOTOR_DIR_LEFT_PIN = 6
MOTOR_DIR_RIGHT_PIN = 15
BATTERY_ADC_PIN = 1
