# device_code

This folder is the deployment-only package for boards.

Included:
1. Runtime firmware modules and packages only (`main.py`, `config.py`, `runtime_config.py`, `app/`, `boards/`, `drivers/`, `net/`, `protocol/`, `radio/`).
2. `support/` for runtime helpers previously under `utils/` (`logger`, `timebase`, `ringbuffer`).

Excluded by design:
1. `tests/`
2. `tools/`
3. docs (`*.md`) outside this file
4. logs
5. host-only artifacts (`.pytest_cache`, `__pycache__`)

Deployment:
1. Copy the parent folder `toDevice` to board storage layout as: `toDevice/code.py` -> `/code.py` and `toDevice/device_code/` -> `/device_code/`.
2. Edit `/code.py` per node role, ID, and board profile.
3. Ensure `/device_code/config.py` has the correct `RADIO_BACKEND` for that device.
