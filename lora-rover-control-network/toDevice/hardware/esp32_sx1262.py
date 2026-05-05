try:
    from typing import override
except ImportError:
    def override(func):
        return func
    
from hardware.base import HardwarePlatform


class ESP32SX1262Hardware(HardwarePlatform):
    """Hardware profile mapped from ESP32"""
    def __init__(self, group_id, node_id, freq_base=900.0, freq_step=1.0):
        super().__init__(group_id, node_id, freq_base=freq_base, freq_step=freq_step)

    @property
    @override
    def board_name(self):
        return "esp32_sx1262"

# ======= SETUPS ============

    @override
    def setup_pins(self):
        import board
        import microcontroller

        self._pins = {
            "sck": board.D8,
            "miso": board.D9,
            "mosi": board.D10,
            "rst": board.D1,
            "nss": microcontroller.pin.GPIO41,
            "busy": microcontroller.pin.GPIO40,
            "dio1": microcontroller.pin.GPIO39,
            "rf_sw": microcontroller.pin.GPIO38,
        }
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

    @override
    def build_endpoint_capabilities(self, runtime_config):
        capabilities = {}
        actuator = getattr(runtime_config, "ENDPOINT_ACTUATOR", "pwm_servo")
        if actuator == "pwm_servo" and getattr(runtime_config, "ENDPOINT_ENABLE_PWM_SERVO", False):
            try:
                from hardware.actuators import PwmServoActuator

                capabilities["servo"] = PwmServoActuator(
                    pin_name=getattr(runtime_config, "ENDPOINT_SERVO_PIN", "D7"),
                    min_us=getattr(runtime_config, "ENDPOINT_SERVO_MIN_US", 500),
                    max_us=getattr(runtime_config, "ENDPOINT_SERVO_MAX_US", 2500),
                )
            except Exception as exc:
                print("endpoint servo unavailable: {0}".format(exc))
        elif actuator == "bus_servo":
            try:
                from hardware.actuators import BusServoActuator

                capabilities["servo"] = BusServoActuator(
                    tx_pin_name=getattr(runtime_config, "ENDPOINT_BUS_SERVO_TX_PIN", "D7"),
                    rx_pin_name=getattr(runtime_config, "ENDPOINT_BUS_SERVO_RX_PIN", "D6"),
                    baudrate=getattr(runtime_config, "ENDPOINT_BUS_SERVO_BAUDRATE", 1000000),
                    servo_id=getattr(runtime_config, "ENDPOINT_BUS_SERVO_ID", 1),
                )
            except Exception as exc:
                print("endpoint bus servo unavailable: {0}".format(exc))
        return capabilities
    
# ====== COMMUNICATION ========


# ===== MISCELLANEOUS ========    
