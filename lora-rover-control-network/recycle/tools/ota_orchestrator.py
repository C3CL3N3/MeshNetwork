# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""End-to-end OTA orchestration helper for physical board tests.

Default mode is dry-run: print commands for each node.
Use --execute to run commands with subprocess.
"""

import argparse
import subprocess


SCENARIOS = {
    "two-node": [
        {"role": "controller", "node_id": 1, "name": "controller"},
        {"role": "rover", "node_id": 2, "name": "virtual-rover"},
    ],
    "one-relay": [
        {"role": "controller", "node_id": 1, "name": "controller"},
        {"role": "relay", "node_id": 10, "name": "relay-a"},
        {"role": "rover", "node_id": 2, "name": "virtual-rover"},
    ],
    "two-relay": [
        {"role": "controller", "node_id": 1, "name": "controller"},
        {"role": "relay", "node_id": 10, "name": "relay-a"},
        {"role": "relay", "node_id": 11, "name": "relay-b"},
        {"role": "rover", "node_id": 2, "name": "virtual-rover"},
    ],
    "drone-relay": [
        {"role": "controller", "node_id": 1, "name": "controller"},
        {"role": "relay", "node_id": 20, "name": "drone-relay"},
        {"role": "rover", "node_id": 2, "name": "rover"},
    ],
}


def build_node_commands(port, role, node_id, project_root="."):
    sync_cmd = [
        "mpremote",
        "connect",
        port,
        "fs",
        "cp",
        "-r",
        project_root,
        ":/app",
    ]

    config_cmd = [
        "mpremote",
        "connect",
        port,
        "exec",
        (
            "import sys;sys.path.insert(0,'/app');"
            "import runtime_config as r;"
            "c=r.get_runtime_config();"
            "print(c.parse_command('ROLE:{0}'));"
            "print(c.parse_command('NODE:{1}'));"
            "print(c.status())"
        ).format(role, node_id),
    ]

    run_cmd = [
        "mpremote",
        "connect",
        port,
        "exec",
        "import sys;sys.path.insert(0,'/app');import main;main.main()",
    ]

    return {
        "sync": sync_cmd,
        "config": config_cmd,
        "run": run_cmd,
    }


def build_plan(scenario, ports, project_root="."):
    if scenario not in SCENARIOS:
        raise ValueError("unknown scenario: {0}".format(scenario))
    layout = SCENARIOS[scenario]
    if len(ports) < len(layout):
        raise ValueError("scenario {0} needs at least {1} ports".format(scenario, len(layout)))

    plan = []
    for idx, node in enumerate(layout):
        port = ports[idx]
        commands = build_node_commands(port, node["role"], node["node_id"], project_root=project_root)
        plan.append({"node": node, "port": port, "commands": commands})
    return plan


def print_plan(plan):
    for item in plan:
        node = item["node"]
        print("\n[{0}] role={1} node_id={2} port={3}".format(node["name"], node["role"], node["node_id"], item["port"]))
        for stage in ("sync", "config", "run"):
            print("  {0}: {1}".format(stage, " ".join(item["commands"][stage])))


def execute_plan(plan, stop_on_error=True):
    for item in plan:
        node = item["node"]
        for stage in ("sync", "config", "run"):
            cmd = item["commands"][stage]
            print("RUN [{0}:{1}] {2}".format(node["name"], stage, " ".join(cmd)))
            result = subprocess.run(cmd, check=False)
            if result.returncode != 0 and stop_on_error:
                raise RuntimeError("command failed for node={0} stage={1}".format(node["name"], stage))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="OTA orchestration for multi-node LoRa tests")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS.keys()), default="two-node")
    parser.add_argument("--ports", required=True, help="Comma-separated serial ports, e.g. COM5,COM8")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--execute", action="store_true", help="Execute commands; otherwise dry-run")
    parser.add_argument("--continue-on-error", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    ports = [p.strip() for p in args.ports.split(",") if p.strip()]
    plan = build_plan(args.scenario, ports, project_root=args.project_root)
    print_plan(plan)
    if args.execute:
        execute_plan(plan, stop_on_error=not args.continue_on_error)


if __name__ == "__main__":
    main()
