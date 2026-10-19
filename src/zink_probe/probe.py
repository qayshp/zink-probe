"""Session orchestration, isolated from hardware for deterministic transcript tests."""

from .protocol import ATTRIBUTES, SELECT, ProtocolError, check_response, decode_fields


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


async def read_identity(connection):
    identity = {}
    errors = {}
    # Individual reads keep unsupported optional attributes from blocking all identity.
    for tag, (name, _) in ATTRIBUTES.items():
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
