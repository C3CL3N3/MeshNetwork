# Adaptive-SF Multi-Hop LoRa Rover

This repository contains a Python-first firmware scaffold for identical LoRa nodes that can run as:
- controller
- relay
- rover
- observer


## Structure

- `toDevice/`: deployment-ready payload for boards
- `toDevice/code.py`: boot entry script (edit per node role/id/profile)
- `toDevice/device_code/`: canonical on-device runtime modules
- `toDevice/device_code/main.py`: startup entry point and main loop skeleton
- `toDevice/device_code/config.py`: compile-time-like constants and defaults
- `toDevice/device_code/runtime_config.py`: runtime role override parser
- `toDevice/device_code/radio/`, `toDevice/device_code/protocol/`, `toDevice/device_code/net/`, `toDevice/device_code/app/`, `toDevice/device_code/boards/`, `toDevice/device_code/support/`: layered modules
- `tests/`: host-side tests
- `tools/`: host-side scripts (simulation, monitor, orchestration)

## Runtime Role Selection

- Default role comes from `toDevice/device_code/config.DEFAULT_ROLE`.
- Override at boot/runtime with simple text commands handled by `toDevice/device_code/runtime_config.py`:
  - `ROLE:controller`
  - `ROLE:relay`
  - `ROLE:rover`
  - `ROLE:observer`
  - `STATUS`

## Radio and BLE Defaults

- LoRa defaults now follow the lab group plan in `toDevice/device_code/config.py`.
- Group ID is set to `13` by default, which also drives the base frequency used by all nodes.
- The controller role supports an optional BLE command bridge when `adafruit_ble` is available on the board.
- Controller setup initializes BLE and starts advertising immediately; the tick loop then polls the BLE control characteristic for commands.
- LoRa receive polling uses a longer timeout to match the working lab-style listen loop.

## Notes

- Controller and relay role apps now include basic operational behavior.
- SX1262 MicroPython backend now includes hardware setup and driver probing hooks.
- OTA command planning/execution helper is available at `tools/ota_orchestrator.py`.

## OTA Orchestration

Dry-run examples:

- `python tools/ota_orchestrator.py --scenario two-node --ports COM5,COM8`
- `python tools/ota_orchestrator.py --scenario one-relay --ports COM5,COM8,COM9`

Execute example:

- `python tools/ota_orchestrator.py --scenario two-node --ports COM5,COM8 --execute`

## Exploration Document

- See [explorations.md](explorations.md) for:
  - full technical summary
  - engineering decisions and rationale
  - information exchange model
  - bidirectional rover/controller discussion
  - dual-controller considerations
  - precise test plans for 2 devices, relay setups, rover, and drone relay scenarios

## Lab Checklist

- See [lab_checklist.md](lab_checklist.md) for a practical pass/fail execution sheet you can use during bench and field experiments.

## Hardware Setup Guide

- See [setup_hw_guide.md](setup_hw_guide.md) for step-by-step flashing, deployment, role setup, OTA orchestration, and live monitoring instructions.
