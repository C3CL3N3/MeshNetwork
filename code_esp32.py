# SPDX-FileCopyrightText: 2026 Student Lab - COMP 4531 - HKUST
# SPDX-License-Identifier: MIT

import busio
import digitalio
import microcontroller
import board
import time
from sx1262 import SX1262

# --- GROUP IDENTITY ---
GROUP_ID = 0  # <--- STUDENTS CHANGE THIS (1 to 30)

# --- CONFIGURATION ---
FREQ_BASE = 900.0
FREQ_STEP = 1.0
MY_FREQ = FREQ_BASE + (GROUP_ID - 1) * FREQ_STEP

BW = 125.0
SF = 7      # Must match the transmitter's SF
CR = 5

# --- PINS ---
sck_pin   = board.D8
miso_pin  = board.D9
mosi_pin  = board.D10
rst_pin   = board.D1
nss_pin   = microcontroller.pin.GPIO41
busy_pin  = microcontroller.pin.GPIO40
dio1_pin  = microcontroller.pin.GPIO39
rf_sw_pin = microcontroller.pin.GPIO38

# --- SETUP ---
# For receiving, we usually set the RF switch to RX mode 
# (On many boards, this is False/Low, check your specific hardware schematic)
rf_switch = digitalio.DigitalInOut(rf_sw_pin)
rf_switch.direction = digitalio.Direction.OUTPUT
rf_switch.value = False  # Set to False for RX 

spi = busio.SPI(sck_pin, mosi_pin, miso_pin)

lora = SX1262(
    spi, sck_pin, mosi_pin, miso_pin,
    nss_pin, dio1_pin, rst_pin, busy_pin
)

# Initialize at the group's specific frequency
lora.begin(freq=MY_FREQ, bw=BW, sf=SF, cr=CR, useRegulatorLDO=True, tcxoVoltage=1.8)

print(f"--- Group {GROUP_ID} Receiver Initialized ---")
print(f"Listening on {MY_FREQ} MHz...")

# --- MAIN RECEIVE LOOP ---
print("Waiting for messages...")
while True:
    # Some libraries use .get_irq_status() or simply .recv() 
    # For many SX1262 drivers, we call .recv() which returns data if available
    
    data, status = lora.recv() # This returns a tuple (payload, status)
    
    if data:
        try:
            # Decode the received bytes
            message = data.decode('utf-8')
            
            # Get signal quality
            rssi = lora.getRSSI()
            snr = lora.getSNR()
            
            print("-" * 40)
            print(f"Message: {message}")
            print(f"RSSI: {rssi} dBm | SNR: {snr} dB")
            
        except Exception as e:
            print(f"Received data, but error decoding: {data}")
            
    time.sleep(0.1)