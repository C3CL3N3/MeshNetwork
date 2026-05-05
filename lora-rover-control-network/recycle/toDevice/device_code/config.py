# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Global constants and defaults for Prompt 1 scaffold."""

# Node identity defaults (override per device in production)
DEFAULT_NODE_ID = 1
DEFAULT_ROLE = "controller"  # controller | relay | rover | observer
DEFAULT_MODE = "throughput"  # speed | throughput

# LoRa defaults (group-based lab channel plan)
LORA_GROUP_ID = 13
LORA_GROUP_BASE_MHZ = 900.0
LORA_GROUP_STEP_MHZ = 1.0
LORA_FREQUENCY_HZ = int((LORA_GROUP_BASE_MHZ + (LORA_GROUP_ID - 1) * LORA_GROUP_STEP_MHZ) * 1000000)
LORA_BANDWIDTH_HZ = 125000
LORA_CODING_RATE = 5
LORA_DEFAULT_SF = 9
LORA_MIN_SF = 7
LORA_MAX_SF = 12

# Radio/board profile selection
BOARD_PROFILE = "esp32s3_sx1262"  # generic | esp32s3_sx1262 | nrf52840_sx1262
RADIO_BACKEND = "circuitpython"  # stub | micropython | circuitpython
VALID_BOARD_PROFILES = ("generic", "esp32s3_sx1262", "nrf52840_sx1262")

# Runtime loop and safety defaults
LOOP_SLEEP_MS = 20
RADIO_RECEIVE_TIMEOUT_MS = 300
WATCHDOG_STOP_MS = 500
MAX_MOTOR_PWM = 255
TURN_SCALE_NUM = 3
TURN_SCALE_DEN = 5

# Simple chat mode: controller/endpoints send raw text from supervisor serial,
# relay forwards raw packets, advanced routing remains disconnected.
SIMPLE_CHAT_MODE = True

# Optional BLE command bridge defaults for controller nodes.
BLE_GROUP_ID = LORA_GROUP_ID
BLE_DEVICE_PREFIX = "LoRaLab"
BLE_CONTROL_POLL_MS = 50

# Forwarding and ACK behavior
FORWARD_MAX_RETRIES = 3
ACK_TIMEOUT_MS = 250
ACK_GAP_MS = 40
BACKOFF_BASE_MS = 10
BACKOFF_MAX_MS = 120

# Routing/neighbor caps to avoid unbounded growth in critical loop
MAX_NEIGHBORS = 16
MAX_RECENT_SEQS = 64
MAX_TX_QUEUE = 16

# Packet format constraints
MAX_PACKET_PAYLOAD = 48
DEFAULT_PACKET_TTL = 8

# Role-specific compile-time-like defaults
ROLE_CAPABILITIES = {
    "controller": {"is_sink": True, "can_forward": False},
    "relay": {"is_sink": False, "can_forward": True},
    "rover": {"is_sink": False, "can_forward": False},
    "observer": {"is_sink": False, "can_forward": False},
}

VALID_ROLES = tuple(ROLE_CAPABILITIES.keys())
VALID_MODES = ("speed", "throughput")
