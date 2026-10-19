import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from .ble import BleConnection, discover
from .probe import negotiate, read_identity, read_status, require_select
from .rfcomm import RfcommConnection
from .trace import Trace


def parser():
    p = argparse.ArgumentParser(
        description="Read-only HP Sprocket Select Bluetooth probe"
    )
    p.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("discover", "probe"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--scan-seconds", type=float, default=10)
        cmd.add_argument(
            "--log", type=Path, help="New private JSONL file (never overwritten)"
        )
        if name == "probe":
            cmd.add_argument("--ble-id", help="macOS BLE UUID from discover")
            cmd.add_argument(
                "--timeout", type=float, default=10, help="Per-response deadline"
            )
    return p


async def run(args, trace, result):
    candidates = await discover(args.scan_seconds, trace)
    result["devices"] = [entry for _, entry in candidates]
    if args.command == "discover":
        result["ok"] = True
        return 0
    if args.ble_id:
        matches = [
            (d, e) for d, e in candidates if e["ble_id"].lower() == args.ble_id.lower()
        ]
    else:
        matches = [(d, e) for d, e in candidates if e["select_advertisement"]]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one Select candidate, found {len(matches)}. "
            "Run discover, then use --ble-id UUID if identification is absent or ambiguous."
        )
    device, entry = matches[0]
    result["selected"] = entry
    ble = BleConnection(device, args.timeout, trace)
    rfcomm = None
    try:
        await ble.open()
        result["ble"] = {"session": await negotiate(ble, "ble", trace)}
        identity, errors = await read_identity(ble)
        result["ble"].update(identity=identity, attribute_errors=errors)
        require_select(identity)
        result["ble"]["status"] = await read_status(ble)
        address = identity.get("bluetooth_mac")
        if not address or address in ("00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"):
            raise RuntimeError(
                "No usable protocol-reported MAC; cannot safely map RFCOMM target"
            )
        rfcomm = RfcommConnection(address, args.timeout, trace)
        await rfcomm.open()
        result["rfcomm"] = {"session": await negotiate(rfcomm, "rfcomm", trace)}
        identity, errors = await read_identity(rfcomm)
        result["rfcomm"].update(identity=identity, attribute_errors=errors)
        require_select(identity)
        result["rfcomm"]["status"] = await read_status(rfcomm)
        missing = []
        for transport in ("ble", "rfcomm"):
            data = result[transport]
            for name in ("firmware", "bluetooth_mac"):
                if not data["identity"].get(name):
                    missing.append(f"{transport}.identity.{name}")
            for name in ("battery_percent", "print_status_code"):
                if name not in data["status"]:
                    missing.append(f"{transport}.status.{name}")
        if missing:
            raise RuntimeError(f"Required fields missing: {', '.join(missing)}")
        result["ok"] = True
        return 0
    finally:
        # Each cleanup gets a chance even if the other fails.
        for connection in (rfcomm, ble):
            if connection is not None:
                try:
                    await connection.close()
                except Exception as exc:
                    trace.event("cleanup_error", error=str(exc))


def main():
    p = parser()
    args = p.parse_args()
    if args.scan_seconds <= 0 or getattr(args, "timeout", 1) <= 0:
        p.error("Timeouts must be positive")
    if sys.platform != "darwin":
        p.error("Hardware CLI currently supports macOS only")
    path = args.log or Path("logs") / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ") + f"-{args.command}.jsonl"
    )
    try:
        trace = Trace(path)
    except OSError as exc:
        p.exit(2, f"Cannot create trace: {exc}\n")
    result = {"ok": False, "command": args.command, "log": str(path.resolve())}
    code = 1
    try:
        trace.event("start", command=args.command, read_only=True)
        code = asyncio.run(run(args, trace, result))
    except KeyboardInterrupt:
        result["error"] = "Interrupted; no request retried"
        code = 130
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        trace.event("result", **result)
        trace.close()
    print(json.dumps(result, indent=2))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
