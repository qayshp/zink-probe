"""Install a per-user, capture-only Linux IPP service. Never enables Bluetooth.

System CUPS registration is a separate displayed lpadmin command, which may
require administrator authorization. No sudo, password handling or live mode.
"""

import argparse
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


def unit_quote(value):
    value = str(value)
    if any(ord(c) < 32 for c in value):
        raise ValueError("Service arguments cannot contain control characters")
    return (
        '"'
        + value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("%", "%%")
        .replace("$", "$$")
        + '"'
    )


def plan(binary, python, root, layout, port):
    if layout not in ("fill", "preserve-edges") or not 1024 <= port <= 65535:
        raise ValueError("Invalid capture layout or port")
    root = root.expanduser().resolve() / f"{layout}-capture"
    name = f"zink-select-{layout}-capture.service"
    queue = "HP_Sprocket_Select_" + (
        "Preserve_Edges_Capture" if layout == "preserve-edges" else "Borderless_Capture"
    )
    command = [
        str(binary.resolve()),
        str(python.absolute()),
        str(root / "config.json"),
        str(root / "incoming"),
        str(root / "spool"),
        str(root / "bridge.log"),
        str(port),
    ]
    unit = f"""[Unit]
Description=HP Sprocket Select {layout} CAPTURE ONLY
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=simple
ExecStart={" ".join(unit_quote(x) for x in command)}
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6

[Install]
WantedBy=default.target
"""
    register = [
        shutil.which("lpadmin") or "/usr/sbin/lpadmin",
        "-p",
        queue,
        "-E",
        "-v",
        f"ipp://127.0.0.1:{port}/ipp/print",
        "-m",
        "everywhere",
        "-o",
        "printer-is-shared=false",
        "-o",
        "printer-error-policy=abort-job",
        "-D",
        f"HP Sprocket Select ({layout}) (capture)",
    ]
    return root, name, unit, register


def install(binary, python, root, layout, port, unit_directory):
    if sys.platform != "linux":
        raise ValueError("Installation requires Linux with a systemd user session")
    root, name, unit, register = plan(binary, python, root, layout, port)
    unit_path = unit_directory.expanduser().absolute() / name
    if root.exists() or unit_path.exists():
        raise ValueError(
            "Capture data or service already exists; preserve and inspect it"
        )
    subprocess.run(
        ["systemctl", "--user", "show-environment"], check=True, capture_output=True
    )
    version = subprocess.check_output([str(binary.resolve()), "--version"], text=True)
    if not version.startswith("zink-ipp "):
        raise ValueError("Expected the project's zink-ipp executable")
    subprocess.run(
        [str(python.absolute()), "-c", "import PIL, zink_probe.ipp_worker"], check=True
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))
    old_umask = os.umask(0o077)
    try:
        root.mkdir(parents=True)
        for directory in ("incoming", "jobs", "spool"):
            (root / directory).mkdir()
        (root / "config.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "mode": "capture",
                    "data_dir": str(root),
                    "preparation_mode": layout,
                },
                indent=2,
            )
            + "\n"
        )
        unit_path.parent.mkdir(parents=True, exist_ok=True)
        with unit_path.open("x") as file:
            file.write(unit)
    finally:
        os.umask(old_umask)
    # Failures deliberately retain data/configuration for inspection. No overwrite
    # or automated live-mode conversion/replay is available in this installer.
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", name], check=True)
    for _ in range(40):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.25)
    else:
        raise TimeoutError(
            f"Capture listener failed to start; inspect journalctl --user -u {name}"
        )
    print(
        json.dumps(
            {"service": name, "data": str(root), "mode": "capture", "port": port}
        )
    )
    print(
        "Next, register this capture endpoint with system CUPS (may need administrator authorization):"
    )
    print(shlex.join(register))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument(
        "--root", type=Path, default=Path.home() / ".local/share/zink-probe"
    )
    parser.add_argument(
        "--unit-directory", type=Path, default=Path.home() / ".config/systemd/user"
    )
    parser.add_argument(
        "--layout", choices=("fill", "preserve-edges"), default="preserve-edges"
    )
    parser.add_argument("--port", type=int, default=8632)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    if args.plan_only:
        root, name, unit, register = plan(
            args.binary, args.python, args.root, args.layout, args.port
        )
        print(
            json.dumps(
                {
                    "root": str(root),
                    "service": name,
                    "unit": unit,
                    "register": register,
                },
                indent=2,
            )
        )
    else:
        install(
            args.binary,
            args.python,
            args.root,
            args.layout,
            args.port,
            args.unit_directory,
        )
