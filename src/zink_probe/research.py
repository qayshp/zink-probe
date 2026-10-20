"""Bounded, explicitly requested read-only protocol experiments."""

import asyncio
import time

from .probe import read_config, read_status
from .protocol import ERROR_NAMES, RESEARCH_REQUESTS


async def investigate(connection, records=None, trace=None):
    records = [] if records is None else records
    for request in RESEARCH_REQUESTS:
        try:
            response = await connection.exchange(request)
        except Exception as exc:
            record = {
                "request": request.hex(),
                "outcome": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
            records.append(record)
            if trace is not None:
                trace.event("experiment", **record)
            raise
        record = {"request": request.hex(), "response": response.hex()}
        if len(response) == 3 and response[:2] == bytes([1, request[0]]):
            record.update(outcome="rejected", error_code=response[2])
            record["error_name"] = ERROR_NAMES.get(response[2], "unknown")
        elif response and response[0] == request[0] + 1:
            record["outcome"] = "returned"
        else:
            record["outcome"] = "unexpected"
            records.append(record)
            break
        records.append(record)
        if trace is not None:
            trace.event("experiment", **record)
        await asyncio.sleep(0.1)
    return records


async def observe(ble, rfcomm, seconds, trace):
    samples = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        sample = {
            "elapsed_seconds": seconds - max(0, end - time.monotonic()),
            "ble": await read_status(ble),
            "rfcomm": await read_status(rfcomm),
        }
        samples.append(sample)
        trace.event("observation", **sample)
        await asyncio.sleep(min(10, max(0, end - time.monotonic())))
    # Check configuration was not altered during our own diagnostic requests.
    return {"samples": samples, "configuration_after": await read_config(rfcomm)}
