"""Explicit, bounded settings experiments; normal probe sessions remain read-only."""

from .capabilities import read_capabilities, read_metrics
from .probe import read_config, read_status
from .protocol import (
    SELECT_LED_COLORS,
    ProtocolError,
    check_response,
    safe_config_write,
)


async def snapshots(connections):
    return {name: await read_config(c) for name, c in connections.items()}


async def expect_setting(connections, key, value):
    result = await snapshots(connections)
    for name, config in result.items():
        if config["errors"] or config["values"].get(key) != value:
            raise ProtocolError(f"{name} {key} readback did not match {value!r}")
    return result


async def roundtrip(connections, writer, key, request, restore, value, original, trace):
    if not all(safe_config_write(m) for m in (request, restore)):
        raise ProtocolError("Setting/original value is outside bounded write policy")
    record = {"key": key, "writer": writer, "original": original, "temporary": value}
    other = next(name for name in connections if name != writer)
    for c in connections.values():
        c.config_writes.update((request, restore))
    trace.event("config_write_grant", requests=[request.hex(), restore.hex()])
    try:
        try:
            # Restore even if a write takes effect but its acknowledgement is lost.
            response = await connections[writer].exchange(request)
            check_response(request, response)
            record["write_reply"] = response.hex()
            record["temporary_readback"] = await expect_setting(connections, key, value)
        except Exception as exc:
            record["experiment_error"] = f"{type(exc).__name__}: {exc}"
        finally:
            record["restore_attempts"] = []
            for name in (other, writer):
                try:
                    response = await connections[name].exchange(restore)
                    check_response(restore, response)
                    record["restore_attempts"].append(
                        {"transport": name, "reply": response.hex()}
                    )
                    record["restored_readback"] = await expect_setting(
                        connections, key, original
                    )
                    record["restored"] = True
                    break
                except Exception as exc:
                    record["restore_attempts"].append(
                        {"transport": name, "error": f"{type(exc).__name__}: {exc}"}
                    )
            if not record.get("restored"):
                record["restored"] = False
    finally:
        for c in connections.values():
            c.config_writes.difference_update((request, restore))
        trace.event("config_write_revoke", result=record)
    return record


async def settings_test(ble, rfcomm, trace, result):
    connections = {"ble": ble, "rfcomm": rfcomm}
    result["before"] = await snapshots(connections)
    before = result["before"]
    if before["ble"] != before["rfcomm"] or before["ble"]["errors"]:
        raise ProtocolError(
            "Cannot start settings test with differing/invalid configuration"
        )
    result["capabilities"] = {}
    result["metrics_before"] = {}
    for name, connection in connections.items():
        status = await read_status(connection)
        jobs = await connection.exchange(b"\x2c")
        if (
            status.get("print_status_code") != 1
            or status.get("current_job_id") != 0
            or status.get("queue_status_code") != 1
            or jobs != b"\x2d"
        ):
            raise ProtocolError(
                "Settings test requires idle printer and empty remote queue"
            )
        capabilities = await read_capabilities(connection)
        table = capabilities.get("table", {})
        if 28 not in table.get("requests", []) or not {1, 3}.issubset(
            table.get("sys_cfg", [])
        ):
            raise ProtocolError("Device does not advertise the required config writes")
        palette = table.get("color_palette", [])
        if not all("#" + color.hex() in palette for color in SELECT_LED_COLORS):
            raise ProtocolError(
                "Select color palette does not match the bounded policy"
            )
        result["capabilities"][name] = capabilities
        result["metrics_before"][name] = await read_metrics(connection)
        if not {"1", "3"}.issubset(result["metrics_before"][name].get("values", {})):
            raise ProtocolError(
                "Page/calibration counters unavailable before settings test"
            )
    original = before["ble"]["values"]
    sleep = original["sleep_timer_minutes"]
    color = bytes(original["led_rgb"])
    alternative_sleep = 5 if sleep != 5 else 3
    alternative_color = next(c for c in SELECT_LED_COLORS[1:] if c != color)
    experiments = [
        (
            "ble",
            "sleep_timer_minutes",
            b"\x1c\x01" + alternative_sleep.to_bytes(2, "little"),
            b"\x1c\x01" + sleep.to_bytes(2, "little"),
            alternative_sleep,
            sleep,
        ),
        (
            "rfcomm",
            "led_rgb",
            b"\x1c\x03" + alternative_color,
            b"\x1c\x03" + color,
            list(alternative_color),
            list(color),
        ),
    ]
    # Validate ALL original values before any mutation, so restoration is authorized.
    if not all(safe_config_write(m) for e in experiments for m in e[2:4]):
        raise ProtocolError(
            "Original settings cannot be restored by this bounded policy"
        )
    trace.event("settings_baseline", configuration=before)
    result["experiments"] = []
    for experiment in experiments:
        record = await roundtrip(connections, *experiment, trace)
        result["experiments"].append(record)
        if not record.get("restored") or "experiment_error" in record:
            raise ProtocolError(
                "Settings experiment failed; inspect restoration result"
            )
    result["after"] = await snapshots(connections)
    result["metrics_after"] = {n: await read_metrics(c) for n, c in connections.items()}
    if result["after"] != before:
        raise ProtocolError(
            "Full configuration did not match original after restoration"
        )
    for name in connections:
        for key in ("1", "3"):
            a = result["metrics_before"][name].get("values", {}).get(key)
            b = result["metrics_after"][name].get("values", {}).get(key)
            if a is None or a != b:
                raise ProtocolError("Page/calibration counters changed or unavailable")
    result["restored"] = True
