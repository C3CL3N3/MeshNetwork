# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""nRF52840 + SX1262 board mapping placeholders."""

class _Pin:
	def __init__(self, name):
		self.name = name


try:
	import board  # type: ignore
except Exception:
	class _Board:
		D1 = _Pin("D1")
		D2 = _Pin("D2")
		D3 = _Pin("D3")
		D4 = _Pin("D4")
		D5 = _Pin("D5")
		D8 = _Pin("D8")
		D9 = _Pin("D9")
		D10 = _Pin("D10")

	board = _Board()

BOARD_NAME = "nrf52840_sx1262"

LORA_DIO1_PIN = getattr(board, "D1", _Pin("D1"))
LORA_RESET_PIN = getattr(board, "D2", _Pin("D2"))
LORA_BUSY_PIN = getattr(board, "D3", _Pin("D3"))
LORA_CS_PIN = getattr(board, "D4", _Pin("D4"))
LORA_RF_SW_PIN = getattr(board, "D5", _Pin("D5"))
SPI_SCK_PIN = getattr(board, "D8", _Pin("D8"))
SPI_MISO_PIN = getattr(board, "D9", _Pin("D9"))
SPI_MOSI_PIN = getattr(board, "D10", _Pin("D10"))


MOTOR_PWM_LEFT_PIN = 3
MOTOR_PWM_RIGHT_PIN = 4
MOTOR_DIR_LEFT_PIN = 5
MOTOR_DIR_RIGHT_PIN = 6
BATTERY_ADC_PIN = 2
