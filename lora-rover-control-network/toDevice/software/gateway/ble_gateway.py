# SPDX-License-Identifier: MIT

from software import config


class BleGateway:
    def __init__(self, group_id, node_id):
        self.group_id = int(group_id)
        self.node_id = int(node_id)
        self.ble = None
        self.service = None
        self.advertisement = None
        self.ok = False
        self._init_ble()

    def _init_ble(self):
        try:
            import adafruit_ble
            from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
            from adafruit_ble.characteristics import Characteristic
            from adafruit_ble.services import Service
            from adafruit_ble.uuid import VendorUUID

            gid_hex = "{0:02x}".format(self.group_id)

            class MeshService(Service):
                uuid = VendorUUID("13172b58-{0}40-4150-b42d-22f30b0a0499".format(gid_hex))
                cmd_rx = Characteristic(
                    uuid=VendorUUID("13172b58-{0}41-4150-b42d-22f30b0a0499".format(gid_hex)),
                    properties=(Characteristic.WRITE | Characteristic.WRITE_NO_RESPONSE),
                    max_length=config.BLE_NOTIFY_MAX_LEN,
                )
                data_tx = Characteristic(
                    uuid=VendorUUID("13172b58-{0}42-4150-b42d-22f30b0a0499".format(gid_hex)),
                    properties=(Characteristic.READ | Characteristic.NOTIFY),
                    max_length=config.BLE_NOTIFY_MAX_LEN,
                )

            self.ble = adafruit_ble.BLERadio()
            self.ble.name = "{0}{1}".format(config.BLE_NAME_PREFIX, self.group_id)
            self.service = MeshService()
            self.advertisement = ProvideServicesAdvertisement(self.service)
            self.ok = True
        except Exception as exc:
            print("ble unavailable: {0}".format(exc))
            self.ok = False

    @property
    def connected(self):
        return bool(self.ok and self.ble.connected)

    def start(self):
        if self.ok and not self._is_advertising():
            self.ble.start_advertising(self.advertisement)

    def stop(self):
        if self.ok and self._is_advertising():
            self.ble.stop_advertising()

    def _is_advertising(self):
        advertising = getattr(self.ble, "advertising", False)
        if callable(advertising):
            try:
                return bool(advertising())
            except Exception:
                return False
        return bool(advertising)

    def notify(self, msg):
        if not self.connected:
            return
        try:
            self.service.data_tx = str(msg).encode("utf-8")[:config.BLE_NOTIFY_MAX_LEN]
        except Exception:
            pass

    def read_command(self):
        if not self.connected:
            return None
        try:
            value = self.service.cmd_rx
            if value and len(value) > 0:
                self.service.cmd_rx = b""
                return value.decode("utf-8", "ignore").strip().replace("\x00", "")
        except Exception as exc:
            print("ble cmd err: {0}".format(exc))
        return None
