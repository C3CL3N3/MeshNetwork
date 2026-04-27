# SPDX-FileCopyrightText: 2026 Student Lab - COMP 4531 - HKUST
# SPDX-License-Identifier: MIT

import time
import struct
import board
import busio
import digitalio
import audiobusio
import array
import gc
import adafruit_ble
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
from adafruit_ble.services import Service
from adafruit_ble.uuid import VendorUUID
from adafruit_ble.characteristics import Characteristic
from adafruit_lsm6ds.lsm6ds3trc import LSM6DS3TRC
from adafruit_lsm6ds import Rate
from sx1262 import SX1262

# --- GROUP IDENTITY ---
GROUP_ID = 0 # <--- STUDENTS CHANGE THIS (1 to 30)

# --- CONFIGURATION ---
FREQ_BASE = 900.0
FREQ_STEP = 1.0
MY_FREQ = FREQ_BASE + (GROUP_ID - 1) * FREQ_STEP

# --- AUDIO SETTINGS (LOW RAM) ---
HARDWARE_RATE = 16000
# 0.25s chunk = 4000 samples * 2 bytes = 8KB RAM (Very Safe)
RECORD_CHUNK_S = 0.25 
TOTAL_DURATION = 5.0 
TOTAL_LOOPS    = int(TOTAL_DURATION / RECORD_CHUNK_S)

# --- PINS ---
lora_sck = board.D8
lora_miso = board.D9
lora_mosi = board.D10
lora_nss  = board.D4 
lora_rst  = board.D2
lora_busy = board.D3
lora_dio1 = board.D1 
rf_sw_pin = board.D5 

# --- LED ---
led = digitalio.DigitalInOut(board.LED_BLUE)
led.direction = digitalio.Direction.OUTPUT
led.value = True # OFF

# --- 1. SETUP IMU ---
imu_present = False
try:
    if hasattr(board, "IMU_PWR"):
        digitalio.DigitalInOut(board.IMU_PWR).switch_to_output(True)
        time.sleep(0.1)
    i2c = busio.I2C(board.IMU_SCL, board.IMU_SDA, frequency=1000000)
    imu = LSM6DS3TRC(i2c)
    imu.accelerometer_data_rate = Rate.RATE_52_HZ
    imu.gyro_data_rate = Rate.RATE_52_HZ
    imu_present = True
    print("IMU: OK")
except: print("IMU: Failed")

# --- 2. SETUP LORA ---
lora_present = False
try:
    digitalio.DigitalInOut(rf_sw_pin).switch_to_output(False)
    spi = busio.SPI(lora_sck, lora_mosi, lora_miso)
    lora = SX1262(spi, lora_sck, lora_mosi, lora_miso, lora_nss, lora_dio1, lora_rst, lora_busy)
    lora.begin(freq=MY_FREQ, bw=125.0, sf=7, cr=5, useRegulatorLDO=True, tcxoVoltage=1.6)
    print(f"LoRa: OK ({MY_FREQ} MHz)")
    lora_present = True
except: print("LoRa: Failed")

# --- 3. SETUP MIC ---
mic_present = False
raw_buffer = None

try:
    if hasattr(board, "MIC_PWR"):
        digitalio.DigitalInOut(board.MIC_PWR).switch_to_output(True)
        time.sleep(0.1)
    
    clk = board.PDM_CLK if hasattr(board, 'PDM_CLK') else board.D1
    dat = board.PDM_DATA if hasattr(board, 'PDM_DATA') else board.D0
    mic = audiobusio.PDMIn(clk, dat, sample_rate=HARDWARE_RATE, bit_depth=16)
    
    # STATIC ALLOCATION: 8KB
    gc.collect()
    buf_len = int(HARDWARE_RATE * RECORD_CHUNK_S)
    raw_buffer = array.array('H', [0] * buf_len)
    
    print(f"Mic: OK (Buffer: {buf_len} samples)")
    mic_present = True
except Exception as e:
    print(f"Mic Failed: {e}")

# --- 4. BLE SERVICES ---
gid_hex = f"{GROUP_ID:02x}"
IMU_SERVICE_UUID      = VendorUUID(f"13172b58-{gid_hex}40-4150-b42d-22f30b0a0499")
IMU_DATA_CHAR_UUID    = VendorUUID(f"13172b58-{gid_hex}41-4150-b42d-22f30b0a0499")
IMU_CONTROL_CHAR_UUID = VendorUUID(f"13172b58-{gid_hex}42-4150-b42d-22f30b0a0499")
AUDIO_DATA_CHAR_UUID  = VendorUUID(f"13172b58-{gid_hex}44-4150-b42d-22f30b0a0499")

class LabService(Service):
    uuid = IMU_SERVICE_UUID
    imu_data = Characteristic(uuid=IMU_DATA_CHAR_UUID, properties=Characteristic.NOTIFY, max_length=24)
    control = Characteristic(
        uuid=IMU_CONTROL_CHAR_UUID, 
        properties=Characteristic.WRITE | Characteristic.WRITE_NO_RESPONSE | Characteristic.READ | Characteristic.NOTIFY, 
        max_length=50
    )
    audio_data = Characteristic(uuid=AUDIO_DATA_CHAR_UUID, properties=Characteristic.NOTIFY, max_length=200)

ble = adafruit_ble.BLERadio()
ble.name = f"COMP4531_G{GROUP_ID}"
lab_service = LabService()
advertisement = ProvideServicesAdvertisement(lab_service)

# --- HELPERS ---
def blink_led(times=1):
    for _ in range(times):
        led.value = False; time.sleep(0.05); led.value = True; time.sleep(0.05)

def record_and_send_audio():
    if not mic_present or raw_buffer is None: return
    print("Streaming...")
    blink_led(3)
    
    for _ in range(TOTAL_LOOPS):
        # 1. Record 0.25s (Blocking)
        mic.record(raw_buffer, len(raw_buffer))
        
        # 2. Compress (High byte of every 2nd sample)
        # Note: Creating 'compressed' here allocates ~4KB transient RAM.
        # Since we freed everything else, it should fit.
        compressed = bytes([raw_buffer[i] // 256 for i in range(0, len(raw_buffer), 2)])
        
        # 3. Send via BLE
        offset = 0
        while offset < len(compressed):
            try:
                lab_service.audio_data = compressed[offset : offset + 200]
                time.sleep(0.01) # Critical for stability
            except: pass
            offset += 200
            
        # 4. Clean up immediately
        del compressed
        gc.collect()

    try: lab_service.audio_data = b'' 
    except: pass
    print("Done.")

# --- MAIN LOOP ---
mode = "IDLE" 
print(f"Group {GROUP_ID} Ready (Hex: {gid_hex})")

while True:
    ble.start_advertising(advertisement)
    while not ble.connected:
        led.value = False; time.sleep(0.1); led.value = True; time.sleep(0.9)
    ble.stop_advertising()
    print("Connected.")
    blink_led(5) 
    
    lab_service.control = b''
    
    while ble.connected:
        try:
            val = lab_service.control
            if val is not None and len(val) > 0:
                blink_led(1)
                try: cmd = val.decode("utf-8").strip().replace('\x00', '')
                except: cmd = ""
                
                print(f"RX: {cmd}")
                lab_service.control = b'' 
                
                if cmd.startswith("SEND_LORA:") and lora_present:
                    lora.send(bytes(cmd.split(":", 1)[1], "utf-8"))
                elif cmd == "REC_AUDIO":
                    mode = "IDLE"; record_and_send_audio()
                elif cmd == "START":
                    mode = "IMU"
                elif cmd == "STOP":
                    mode = "IDLE"
        except: pass

        if mode == "IMU" and imu_present:
            try:
                ax, ay, az = imu.acceleration
                gx, gy, gz = imu.gyro
                lab_service.imu_data = struct.pack("<ffffff", ax, ay, az, gx, gy, gz)
            except: pass
        
        # Non-blocking check for LoRa (Disabled to prevent freezing if lib blocks)
        # if lora_present: ...
             
        time.sleep(0.001)
    print("Disconnected.")