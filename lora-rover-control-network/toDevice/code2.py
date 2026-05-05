import busio
import digitalio
import microcontroller
import board
import time
import sys
import supervisor
import _bleio
from adafruit_ble import BLERadio
from adafruit_ble.advertising.standard import Advertisement
from hardware import ESP32SX1262Hardware

# --- 1. GROUP IDENTITY (STUDENT EDITABLE) ---
GROUP_ID = 13  # <--- STUDENTS CHANGE THIS (1 to 30)

# --- 2. SETUP HARDWARE ---
hw = ESP32SX1262Hardware(group_id=GROUP_ID, node_id=1)
hw.setup_lora()

# --- 6. INITIAL BOOT MESSAGE ---
print(f"--- Group {GROUP_ID} Node Online ---")
print(f"Broadcasting BLE as: {hw.ble_name}")
hw.lora_send(f"BOOT: Group {GROUP_ID} is online")

# --- 7. MAIN LOOP ---
print("Ready for Serial Input. Type a message and press Enter...")
print("> ", end="")

hw.advertise_ble()

while True:
    # 1. Keep BLE advertising active
    if not hw.is_advertising_ble:
        hw.advertise_ble()
    
    # 2. Read from Serial
    clean_text = hw.read_serial_line()
    if clean_text:
        hw.lora_send(clean_text)

    # 3. Listen for incoming LoRa messages
    hw.receive_lora()

    time.sleep(0.01)