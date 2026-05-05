# SPDX-License-Identifier: MIT
"""Board entrypoint for the fixed-SF7 LoRa mesh firmware — flat-root edition."""

import time
import sys

print("=== mesh boot ===")

try:
    print("import mesh_core...")
    from mesh_core import (
        ESP32SX1262Hardware, NRF52840SX1262Hardware,
        ControllerEndpoint, GadgetEndpoint, RelayEndpoint,
        BleGateway, MeshNetwork, RadioAdapter,
        GROUP_ID, NODE_ID, BOARD_PROFILE, ROLE, ALLOW_EXTERNAL_COMMANDS,
        FREQ_BASE_MHZ, FREQ_STEP_MHZ,
        LORA_BW_KHZ, LORA_SF, LORA_CR, LORA_TX_POWER,
        CONTROL_PREFIXES,
    )
    print("imports ok")
except Exception as _e:
    print("IMPORT FAIL: {0}".format(_e))
    sys.print_exception(_e)
    raise


def build_hardware():
    if BOARD_PROFILE == "esp32_sx1262":
        hw = ESP32SX1262Hardware(GROUP_ID, NODE_ID, FREQ_BASE_MHZ, FREQ_STEP_MHZ)
    else:
        hw = NRF52840SX1262Hardware(GROUP_ID, NODE_ID, FREQ_BASE_MHZ, FREQ_STEP_MHZ)
    hw.setup_pins()
    hw.setup_leds()
    hw.setup_lora(bw=LORA_BW_KHZ, sf=LORA_SF, cr=LORA_CR,
                  power=LORA_TX_POWER,
                  tcxoVoltage=0 if BOARD_PROFILE == "nrf52840_sx1262" else 1.8,
                  debug=(BOARD_PROFILE == "nrf52840_sx1262"))
    return hw


def build_endpoint(role, hw):
    if role == "C":
        return ControllerEndpoint()
    if role == "E":
        return GadgetEndpoint(capabilities=hw.build_endpoint_capabilities())
    return RelayEndpoint()


def _format_payload(node_id, payload):
    if str(payload).startswith(CONTROL_PREFIXES) or str(payload).startswith("PARROT:"):
        return str(payload)
    return "[{0}] {1}".format(node_id, payload)


def handle_command(command, mesh):
    if not command: return
    if command == "ROUTES":
        for dest, route in mesh.routes.items():
            mesh.notify("MESH_ROUTE:{0}|{1}|{2}".format(dest, route["next_hop"], route["hops"]))
        return
    if command == "NEIGHBORS":
        for nid, nb in mesh.neighbors.items():
            mesh.notify("MESH_NB:{0}|{1}|{2:.1f}".format(nid, nb["rssi"], nb["snr"]))
        return
    if command == "TOPOLOGY":
        edges = mesh.topo_tracker.edges()
        if edges:
            parts = ["{0},{1},{2},{3:.1f}".format(a, b, r, s) for a, b, r, s in edges]
            mesh.notify("MESH_TOPOLOGY:" + ";".join(parts))
        else:
            mesh.notify("MESH_TOPOLOGY:none")
        return
    if command.startswith("SEND_NODE:"):
        rest = command[10:]; i = rest.find(":")
        if i > 0:
            try: dst = int(rest[:i])
            except ValueError: mesh.notify("MESH_ERR:BAD_DST:{0}".format(rest[:i])); return
            mesh.send_data(dst, _format_payload(mesh.node_id, rest[i+1:]))
        return
    if command.startswith("SEND_MESH:"):
        mesh.send_data(0, _format_payload(mesh.node_id, command[10:])); return
    if command.startswith("PARROT:"):
        mesh.notify("MESH_PARROT:{0}".format(command[7:])); return
    if command.startswith("TOPO:"):
        mesh.send_data(0, command); return
    if command.startswith("ROUTE_MODE:"):
        mesh.set_route_mode(command[11:], broadcast=True); return
    if command.startswith("SF:"):
        mesh.set_sf(command[3:]); return
    if command.startswith("MODE:"):
        mesh.send_data(0, command); return
    if command.startswith("TO:"):
        parts = command[3:].split(":", 1)
        if len(parts) == 2:
            try: dst = int(parts[0])
            except ValueError: mesh.notify("MESH_ERR:BAD_DST:{0}".format(parts[0])); return
            mesh.send_data(dst, _format_payload(mesh.node_id, parts[1]))
        return
    mesh.send_data(0, _format_payload(mesh.node_id, command))


def handle_local_command(command, mesh, endpoint):
    text = str(command).strip()
    if not text: return
    if text in ("INFO", "STATUS"):
        print(node_info_line(mesh)); return
    if text == "NEIGHBORS":
        if not mesh.neighbors: print("NEIGHBORS:none"); return
        for nid, nb in mesh.neighbors.items():
            print("NEIGHBOR:N{0}|RSSI:{1}|SNR:{2:.1f}".format(nid, nb["rssi"], nb["snr"]))
        return
    if text == "ROUTES":
        if not mesh.routes: print("ROUTES:none"); return
        for dest, route in mesh.routes.items():
            print("ROUTE:N{0}|NH:N{1}|HOPS:{2}|RSSI:{3}|PATH_RSSI:{4}|SCORE:{5:.1f}".format(
                dest, route["next_hop"], route["hops"], route.get("link_rssi", "?"),
                route.get("path_rssi", "?"), route.get("score", 0.0)))
        return
    if text == "TOPOLOGY":
        edges = mesh.topo_tracker.edges()
        if not edges: print("TOPOLOGY:none"); return
        for a, b, r, s in edges:
            print("TOPO_EDGE:N{0}-N{1}|RSSI:{2}|SNR:{3:.1f}".format(a, b, r, s))
        return
    if ALLOW_EXTERNAL_COMMANDS:
        handle_command(text, mesh); return
    if endpoint.on_local_command(text, mesh): return
    print("local command unsupported for role={0}: {1}".format(ROLE, text))


def node_info_line(mesh):
    freq_mhz = FREQ_BASE_MHZ + (GROUP_ID - 1) * FREQ_STEP_MHZ
    return "MESH_INFO:NODE_ID:{0}|SF:{1}|ROLE:{2}|BOARD:{3}|GID:{4}|FREQ:{5}|ROUTE:{6}".format(
        mesh.node_id, mesh._current_sf, ROLE, BOARD_PROFILE, GROUP_ID, freq_mhz, mesh.routes.mode)


def announce_node(mesh):
    info = node_info_line(mesh)
    print(info)
    mesh.notify(info)


def main():
    hw = build_hardware()
    print("hardware ok board={0} node={1}".format(BOARD_PROFILE, NODE_ID))

    radio = RadioAdapter(hw)
    radio.start_rx()

    gateway = BleGateway(GROUP_ID, NODE_ID) if ALLOW_EXTERNAL_COMMANDS else None
    endpoint = build_endpoint(ROLE, hw)
    mesh = MeshNetwork(NODE_ID, radio, endpoint=endpoint, event_sink=gateway, role=ROLE)

    # SF scan — find existing network or start own at LORA_SF
    mesh.scan_for_network()

    freq_mhz = FREQ_BASE_MHZ + (GROUP_ID - 1) * FREQ_STEP_MHZ
    print("Node {0} role={1} board={2} freq={3}MHz SF{4}".format(
        NODE_ID, ROLE, BOARD_PROFILE, freq_mhz, mesh._current_sf))
    announce_node(mesh)

    if gateway is not None and gateway.ok:
        gateway.start()

    gw_was_connected = False
    _last_route_dump = time.monotonic() - 20  # dump immediately on first tick
    while True:
        if gateway is not None and gateway.ok:
            if not gateway.connected:
                gw_was_connected = False
                gateway.start()
            else:
                gateway.stop()
                if not gw_was_connected:
                    gw_was_connected = True
                    announce_node(mesh)
                cmd = gateway.read_command()
                if cmd: handle_command(cmd, mesh)

        serial_cmd = hw.read_serial_line()
        if serial_cmd: handle_local_command(serial_cmd, mesh, endpoint)

        mesh.tick()
        endpoint.tick(mesh)
        mesh.poll_radio()
        # Periodic route/neighbor dump to serial — dashboard builds graph from routing data
        if time.monotonic() - _last_route_dump >= 15.0:
            _last_route_dump = time.monotonic()
            print("ROUTES_DUMP")  # marker so dashboard knows this is a full refresh
            for nid, nb in mesh.neighbors.items():
                print("NEIGHBOR:N{0}|RSSI:{1}|SNR:{2:.1f}".format(nid, nb["rssi"], nb["snr"]))
            for dest, route in mesh.routes.items():
                print("ROUTE:N{0}|NH:N{1}|HOPS:{2}|RSSI:{3}|PATH_RSSI:{4}|SCORE:{5:.1f}".format(
                    dest, route["next_hop"], route["hops"], route.get("link_rssi", "?"),
                    route.get("path_rssi", "?"), route.get("score", 0.0)))
        time.sleep(0.001)


print("starting main...")
try:
    main()
except Exception as exc:
    print("FATAL mesh: {0}".format(exc))
    try: sys.print_exception(exc)
    except Exception: pass
    while True: time.sleep(1)
