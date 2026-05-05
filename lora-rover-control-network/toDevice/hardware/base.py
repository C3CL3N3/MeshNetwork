try:
    from abc import ABC, abstractmethod
except ImportError:
    class ABC:
        pass
    def abstractmethod(func):
        return func
from enum import Enum
import sys

class LoraKeys(Enum):
    SCK = "sck"
    MISO = "miso"
    MOSI = "mosi"
    RST = "rst"
    NSS = "nss"
    BUSY = "busy"
    DIO1 = "dio1"
    RF_SW = "rf_sw"

class HardwarePlatform(ABC):
    """Abstract hardware contract for board-specific implementations.
        Assumes a LoRa supporting device."""

    def __init__(self, group_id, node_id, freq_base=900.0, freq_step=1.0):
        self.group_id = int(group_id)
        self.node_id = node_id
        self.freq_base = float(freq_base)
        self.freq_step = float(freq_step)
        self.lora = None
        self.spi = None
        self.led = None
        self.imu = None
        self.rf_switch = None
        self.mic = None
        self.raw_audio_buffer = None
        self.fft_audio_buffer = None
        self._serial_input_buffer = ""
        self._pins = {}

        self.ble = None
        self.advertisement = None

    def getIdentifier(self):
        return f"G{self.group_id}N{self.node_id}"

    @property
    def frequency_mhz(self):
        return self.freq_base + (self.group_id - 1) * self.freq_step

    @property
    @abstractmethod
    def board_name(self):
        """Human-readable board name."""

# ====== BOOLS ========

    @property
    def has_led(self):
        """Whether this board has a controllable status LED."""
        if self.led:
            return True
        return False
    
    @property
    def has_lora(self):
        """Whether LoRa is active on board."""
        if self.lora:
            return True
        return False

    @property
    def has_imu(self):
        """Whether this board supports IMU setup in this project profile."""
        if self.imu:
            return True
        return False

    @property
    def has_mic(self):
        """Whether this board supports microphone setup in this project profile."""
        if self.mic:
            return True
        return False

    @property
    def has_ble(self):
        """Whether this board profile supports BLE operations."""
        if self.ble:
            return True
        return False

    @property
    def is_advertising_ble(self):
        """Whether BLE is advertising right now."""
        if self.ble:
            return self.ble.advertising()
        return False

# ======= SETUPS ============

    def setup(self):
        """Initialize board peripherals and radio."""
        self.setup_leds()
        self.setup_pins()
        self.setup_lora()
        self.setup_imu()
        self.setup_microphone()

    @abstractmethod
    def setup_pins(self):
        """Setting up a dictionary of pins with keys as in :class:`LoraKeys`."""

    def setup_leds(self):
        """Initializing leds of the device."""
        return False
    
    def setup_lora(self, bw=125.0, sf=7, cr=5, useRegulatorLDO=True, tcxoVoltage=1.8, power=22, debug=False):
        """Initialize SX1262 radio path and switch control. Implemented by default."""
        import busio
        import digitalio
        from sx1262 import SX1262

        if not self._pins:
            print("No pins set up! Can't setup LoRa.")
            return False

        self.rf_switch = digitalio.DigitalInOut(self._pins[LoraKeys.RF_SW.value])
        self.rf_switch.direction = digitalio.Direction.OUTPUT
        self.rf_switch.value = False

        self.spi = busio.SPI(self._pins[LoraKeys.SCK.value], self._pins[LoraKeys.MOSI.value], self._pins[LoraKeys.MISO.value])
        try:
            self.lora = SX1262(
                self.spi,
                self._pins[LoraKeys.SCK.value],
                self._pins[LoraKeys.MOSI.value],
                self._pins[LoraKeys.MISO.value],
                self._pins[LoraKeys.NSS.value],
                self._pins[LoraKeys.DIO1.value],
                self._pins[LoraKeys.RST.value],
                self._pins[LoraKeys.BUSY.value],
                rf_sw=self.rf_switch,
            )
        except TypeError:
            self.lora = SX1262(
                self.spi,
                self._pins[LoraKeys.SCK.value],
                self._pins[LoraKeys.MOSI.value],
                self._pins[LoraKeys.MISO.value],
                self._pins[LoraKeys.NSS.value],
                self._pins[LoraKeys.DIO1.value],
                self._pins[LoraKeys.RST.value],
                self._pins[LoraKeys.BUSY.value],
            )
        self.lora.begin(
            freq=self.frequency_mhz,
            bw=bw,
            sf=sf,
            cr=cr,
            useRegulatorLDO=useRegulatorLDO,
            tcxoVoltage=tcxoVoltage,
            power=power,
            debug=debug,
        )
        if hasattr(self.lora, "recv_start"):
            self.lora.recv_start()
        print("lora ok  {0} MHz  SF{1}".format(self.frequency_mhz, sf))
        return True

    def setup_imu(self):
        """Initialize IMU if supported by the board profile."""
        return False

    def setup_microphone(self):
        """Initialize microphone if supported by the board profile."""
        return False

    def setup_ble(self):
        """Initialize BLE operations."""
        return False

    def build_endpoint_capabilities(self, runtime_config):
        """Return hardware-backed endpoint capabilities for this board."""
        _ = runtime_config
        return {}

# ====== COMMUNICATION ========

    def set_radio_tx_mode(self):
        """Set RF switch for TX path if available."""
        if self.rf_switch is not None:
            self.rf_switch.value = True

    def set_radio_rx_mode(self):
        """Set RF switch for RX path if available."""
        if self.rf_switch is not None:
            self.rf_switch.value = False

    def send_lora_text(self, text):
        """Send UTF-8 text over LoRa."""
        if self.lora is None:
            return False
        try:
            self.set_radio_tx_mode()
            self.lora.send(str(text).encode("utf-8"))
            print(f"\n[TX] Sending: {text} @ {self.frequency_mhz} MHz")
            print("> ", end="")
            return True
        finally:
            self.set_radio_rx_mode()
            if hasattr(self.lora, "recv_start"):
                self.lora.recv_start()

    def lora_send(self, text):
        """Backward-compatible alias used by older lab scripts."""
        return self.send_lora_text(text)

    def receive_lora(self, timeout_ms=300):
        """Receive a LoRa packet if available, else None."""
        if self.lora is None:
            return None
        try:
            result = self.lora.recv(timeout_en=True, timeout_ms=int(timeout_ms))
            if result and isinstance(result, tuple) and len(result) == 2:
                data, _status = result
                try: msg = data.decode("utf-8")
                except: msg = str(data)
                finally:
                    print(f"\n[RX] {msg} | RSSI: {self.lora.getRSSI()} dBm | SNR: {self.lora.getSNR()} dB")
                    print("> ", end="")
                return msg
            return None
        finally:
            if hasattr(self.lora, "recv_start"):
                self.lora.recv_start()
    
    def read_serial_line(self):
        """Read a line from supervisor serial input when available, else None."""
        try:
            import supervisor

            available = int(getattr(supervisor.runtime, "serial_bytes_available", 0))
            if available <= 0:
                return None

            chunk = sys.stdin.read(available)
            if not chunk:
                return None

            self._serial_input_buffer += str(chunk)
            if "\n" not in self._serial_input_buffer and "\r" not in self._serial_input_buffer:
                return None

            line = self._serial_input_buffer.replace("\r", "").replace("\n", "").strip()
            self._serial_input_buffer = ""
            return line if line else None
        except Exception:
            return None

    def advertise_ble(self):
        if self.ble and self.advertisement:
            self.ble.start_advertising(self.advertisement)

    def stop_advertise_ble(self):
        if self.ble and self.advertisement:
            self.ble.stop_advertising()

# ===== MISCELLANEOUS ========

    def blink(self, times=1, on_s=0.05, off_s=0.05):
        _ = (times, on_s, off_s)
        return False

    @property
    def ble_name(self):
        """Default BLE name; subclasses can override board naming rules."""
        return self.getIdentifier()
