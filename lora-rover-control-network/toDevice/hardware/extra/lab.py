from adafruit_ble.uuid import VendorUUID
from adafruit_ble.characteristics import Characteristic
from adafruit_ble.services import Service

GROUP_ID = 13
gid_hex = f"{GROUP_ID:02x}"
IMU_SERVICE_UUID      = VendorUUID(f"13172b58-{gid_hex}40-4150-b42d-22f30b0a0499")
IMU_DATA_CHAR_UUID    = VendorUUID(f"13172b58-{gid_hex}41-4150-b42d-22f30b0a0499")
IMU_CONTROL_CHAR_UUID = VendorUUID(f"13172b58-{gid_hex}42-4150-b42d-22f30b0a0499")
STEP_DATA_CHAR_UUID   = VendorUUID(f"13172b58-{gid_hex}43-4150-b42d-22f30b0a0499")
AUDIO_DATA_CHAR_UUID  = VendorUUID(f"13172b58-{gid_hex}44-4150-b42d-22f30b0a0499")
    
class LabService(Service):
    uuid = IMU_SERVICE_UUID
    imu_data = Characteristic(uuid=IMU_DATA_CHAR_UUID, properties=Characteristic.NOTIFY, max_length=24)
    control = Characteristic(
        uuid=IMU_CONTROL_CHAR_UUID,
        properties=Characteristic.WRITE | Characteristic.WRITE_NO_RESPONSE | Characteristic.READ | Characteristic.NOTIFY,
        max_length=200 
    )
    step_data = Characteristic(uuid=STEP_DATA_CHAR_UUID, properties=Characteristic.NOTIFY, max_length=2)
    audio_data = Characteristic(uuid=AUDIO_DATA_CHAR_UUID, properties=Characteristic.NOTIFY, max_length=200)
