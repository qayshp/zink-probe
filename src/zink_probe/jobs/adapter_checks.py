"""Shared read-only checks for explicit, fresh native adapter connections."""

import argparse
import asyncio
import math

from ..protocol import ProtocolError
from .diagnostics import ReadOnlySession, inspect_printer


def positive_seconds(value):
    value = float(value)
    if not math.isfinite(value) or not 0 < value <= 300:
        raise argparse.ArgumentTypeError("Timeout must be finite and in (0, 300]")
    return value


def device_id(value):
    if len(value) != 32 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise argparse.ArgumentTypeError(
            "Expected 32 hexadecimal protocol device-ID digits"
        )
    return value.lower()


async def run_checks(args, trace, *, stream_factory):
    results = []
    for index in range(args.sessions):
        if index:
            # On the validated Select, immediate reopen can race remote/native
            # teardown even after the close callback. This is a gap between
            # explicitly requested sessions, never a retry of a failed request.
            trace.event("reconnect_settle", seconds=2.0)
            await asyncio.sleep(2.0)
        stream = stream_factory(args.address, timeout=args.timeout, trace=trace)
        session = ReadOnlySession(stream, timeout=args.timeout, trace=trace)
        trace.event("adapter_check_started", session=index + 1)
        try:
            async with asyncio.timeout(args.session_timeout):
                await stream.open()
                result = await inspect_printer(session, args.device_id, trace)
        finally:
            await session.close()
        if stream.close_error:
            raise ConnectionError(stream.close_error)
        if result["session"].get("connection_setup") != "accepted":
            raise ProtocolError("Message limit was not negotiated")
        if result["config_before"]["errors"] or result["config_after"]["errors"]:
            raise ProtocolError("Configuration inspection incomplete")
        if not result["counters_unchanged"] or not result["configuration_unchanged"]:
            raise ProtocolError(
                "Printer counters or configuration changed during check"
            )
        if results:
            previous = results[-1]
            if (
                previous["after"]["pages"] != result["before"]["pages"]
                or previous["after"]["calibrations"] != result["before"]["calibrations"]
                or previous["config_after"] != result["config_before"]
            ):
                raise ProtocolError("Printer state changed between connections")
        result["transport"] = {
            "mtu": stream.mtu,
            "native_writes": stream.native_writes,
            "tx_bytes": stream.tx_bytes,
            "rx_bytes": stream.rx_bytes,
            "closed": stream.state == "closed",
            "close_error": stream.close_error,
        }
        trace.event("adapter_check_result", session=index + 1, result=result)
        results.append(result)
    return results
