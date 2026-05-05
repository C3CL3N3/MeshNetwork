import time

try:
    from typing import override
except ImportError:
    def override(func):
        return func

from hardware.base import HardwarePlatform


class NRF52840SX1262Hardware(HardwarePlatform):
    """Hardware profile mapped from toDevice/code.py."""

    def __init__(self, group_id, node_id, freq_base=900.0, freq_step=1.0):
        super().__init__(group_id, node_id, freq_base=freq_base, freq_step=freq_step)

    @property
    @override
    def board_name(self):
        return "nrf52840_sx1262"

# ======= SETUPS ============

    @override
    def setup_pins(self):
        import board
        self._pins = {
            "sck": board.D8,
            "miso": board.D9,
            "mosi": board.D10,
            "nss": board.D4,
            "rst": board.D2,
            "busy": board.D3,
            "dio1": board.D1,
            "rf_sw": board.D5,
        }
        return True

    @override
    def setup_leds(self):
        import board
        import digitalio

        self.led = digitalio.DigitalInOut(board.LED_BLUE)
        self.led.direction = digitalio.Direction.OUTPUT
        self.led.value = True

    @override
    def setup_imu(self):
        import board
        import busio
        import digitalio
        from adafruit_lsm6ds import Rate
        from adafruit_lsm6ds.lsm6ds3trc import LSM6DS3TRC

        if hasattr(board, "IMU_PWR"):
            digitalio.DigitalInOut(board.IMU_PWR).switch_to_output(True)
            time.sleep(0.1)
        i2c = busio.I2C(board.IMU_SCL, board.IMU_SDA, frequency=1000000)
        self.imu = LSM6DS3TRC(i2c)
        self.imu.accelerometer_data_rate = Rate.RATE_52_HZ
        self.imu.gyro_data_rate = Rate.RATE_52_HZ
        return True

    @override
    def setup_microphone(self):
        import array
        import gc
        import board
        import audiobusio
        import digitalio

        if hasattr(board, "MIC_PWR"):
            digitalio.DigitalInOut(board.MIC_PWR).switch_to_output(True)
            time.sleep(0.1)

        clk = board.PDM_CLK if hasattr(board, "PDM_CLK") else board.D1
        dat = board.PDM_DATA if hasattr(board, "PDM_DATA") else board.D0
        self.mic = audiobusio.PDMIn(clk, dat, sample_rate=16000, bit_depth=16)

        gc.collect()
        self.raw_audio_buffer = array.array("H", [0] * int(16000 * 0.25))
        self.fft_audio_buffer = array.array("H", [0] * 1024)
        return True

    @override
    def setup_ble(self):
        from adafruit_ble import BLERadio
        from adafruit_ble.advertising.standard import Advertisement

        self.ble = BLERadio()
        self.ble.name = self.ble_name
        self.advertisement = Advertisement()
        self.advertisement.short_name = self.ble_name
        return True

    def setup_lab_ble(self):
        from adafruit_ble import BLERadio
        from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
        from hardware.extra.lab import LabService

        self.ble = BLERadio()
        self.ble.name = self.ble_name + "_LAB"

        self.lab_service = LabService()
        self.advertisement = ProvideServicesAdvertisement(self.lab_service)



# ===== MISCELLANEOUS ========

    @override
    def blink(self, times=1, on_s=0.05, off_s=0.05):
        if self.led is None:
            return False
        for _ in range(int(times)):
            self.led.value = False
            time.sleep(float(on_s))
            self.led.value = True
            time.sleep(float(off_s))
        return True
