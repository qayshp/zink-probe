"""Session orchestration, isolated from hardware for deterministic transcript tests."""

from .protocol import (
    ATTRIBUTES,
    CONFIG,
    ERROR_NAMES,
    EXTRA_STATUS_HINTS,
    SELECT,
    ProtocolError,
    bit_view,
    check_response,
    decode_fields,
)


async def negotiate(connection, transport, trace):
    request = b"\x0a\x01\x00" if transport == "ble" else b"\x0a\x02"
    reply = await connection.exchange(request)
    check_response(request, reply)
    request = b"\x24\x00\x10"
    reply = await connection.exchange(request)
    # Known Sprocket 200 firmware quirk; log as observation, not proof of Select behavior.
    if reply[:2] == b"\x01\x24" and len(reply) == 3:
        trace.event("negotiation_rejected", transport=transport, hex=reply.hex())
        return {"connection_setup": "rejected", "raw": reply.hex()}
    check_response(request, reply)
    if len(reply) < 4:
        raise ProtocolError("Truncated CONN_SETUP reply")
    return {
        "connection_setup": "accepted",
        "max_message": int.from_bytes(reply[1:3], "little"),
        "security": reply[3],
    }


async def read_identity(connection, extended=False, identity=None, errors=None):
    identity = {} if identity is None else identity
    errors = {} if errors is None else errors
    # Individual reads keep unsupported optional attributes from blocking all identity.
    for tag, (name, _) in ATTRIBUTES.items():
        if tag == 14 and not extended:
            continue
        request = bytes([4, tag])
        reply = await connection.exchange(request)
        if len(reply) == 3 and reply[:2] == bytes([1, 4]):
            errors[name] = {"rejected": reply.hex()}
            continue
        check_response(request, reply)
        decoded = decode_fields(reply, identity=True)
        if name not in decoded:
            errors[name] = {"missing": reply.hex()}
        identity.update(decoded)
    return identity, errors


async def read_config(connection):
    values, errors = {}, {}
    for tag, (name, _) in CONFIG.items():
        request = bytes([0x1A, tag])
        reply = await connection.exchange(request)
        if len(reply) == 3 and reply[:2] == b"\x01\x1a":
            errors[name] = {"rejected": reply.hex()}
            continue
        check_response(request, reply)
        decoded = decode_fields(reply, config=True)
        if name not in decoded:
            errors[name] = {"missing": reply.hex()}
        values.update(decoded)
    return {"values": values, "errors": errors}


def status_bits(status):
    result = {
        name: bit_view(status[name], width)
        for name, width in (
            ("system_flags", 32),
            ("battery_status_code", 8),
            ("queue_status_code", 8),
        )
        if name in status
    }
    for name, entry in result.items():
        entry["meaning"] = (
            "bitmask; bits 0-4 named in the inspected HP app artifact"
            if name == "system_flags"
            else "enumeration, not independent flags; see decoded status label"
        )
    return result


async def read_copy_progress(connection):
    request = b"\x08\x08"
    reply = await connection.exchange(request)
    if len(reply) == 3 and reply[:2] == b"\x01\x08":
        return {"rejected": reply.hex()}
    check_response(request, reply)
    return decode_fields(reply)


async def read_extra_status(connection):
    result = {}
    for tag, hint in EXTRA_STATUS_HINTS.items():
        request = bytes([8, tag])
        reply = await connection.exchange(request)
        entry = {"tag": tag, "unverified_name_hint": hint, "raw_reply": reply.hex()}
        if len(reply) == 3 and reply[:2] == b"\x01\x08":
            entry["outcome"] = "rejected"
            entry["error_code"] = reply[2]
            entry["error_name"] = ERROR_NAMES.get(reply[2], "unknown")
        else:
            check_response(request, reply)
            entry["outcome"] = "returned" if len(reply) > 1 else "omitted"
        result[f"0x{tag:02X}"] = entry
    return result


async def read_status(connection):
    request = b"\x08\x01\x02\x03\x04\x05\x06\x07\x09"
    reply = await connection.exchange(request)
    check_response(request, reply)
    return decode_fields(reply)


def require_select(identity):
    if identity.get("super_model") != SELECT:
        raise ProtocolError(
            f"Select identity not confirmed (expected 0x{SELECT:04x}, "
            f"got {identity.get('super_model')!r}); stopping"
        )
