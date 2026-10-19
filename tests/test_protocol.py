import asyncio
import json
import stat

import pytest

from zink_probe.probe import negotiate, read_identity, read_status, require_select
from zink_probe.protocol import (
    ATTRIBUTES,
    BleAssembler,
    ProtocolError,
    RfcommParser,
    check_response,
    decode_fields,
    encode_rfcomm,
    validate_request,
)
from zink_probe.trace import Trace


@pytest.mark.parametrize("opcode", [n for n in range(256) if n not in (4, 8, 10, 36)])
def test_other_opcodes_cannot_cross_transport_boundary(opcode):
    with pytest.raises(ProtocolError):
        encode_rfcomm(bytes([opcode, 1]))


@pytest.mark.parametrize(
    "message", [b"", b"\x04", b"\x04\xff", b"\x08\xff", b"\x0a\x03", b"\x24\xff\xff"]
)
def test_allowlist_checks_arguments(message):
    with pytest.raises(ProtocolError):
        validate_request(message)


def wire(payload, large=False):
    return (
        b"HP+"
        + (
            b"\x02" + len(payload).to_bytes(2, "little")
            if large
            else b"\x01" + bytes([len(payload)])
        )
        + payload
    )


def test_rfcomm_all_fragmentation_boundaries_and_combined_frames():
    first = wire(b"\x05\x01\x03abc")
    second = wire(b"\x09\x03\x64", large=True)
    data = first + second
    for split in range(len(data) + 1):
        parser = RfcommParser()
        assert parser.feed(data[:split]) + parser.feed(data[split:]) == [
            b"\x05\x01\x03abc",
            b"\x09\x03\x64",
        ]
        assert parser.buffer == b""
    parser = RfcommParser()
    out = []
    for value in data:
        out.extend(parser.feed(bytes([value])))
    assert len(out) == 2


@pytest.mark.parametrize(
    "bad", [b"BAD!", b"HP+\x03", b"HP+\x01\x00", b"HP+\x02\x01\x10"]
)
def test_malformed_rfcomm_fails_closed(bad):
    with pytest.raises(ProtocolError):
        RfcommParser().feed(bad)


def test_ble_reassembly_ack_and_sequence_error():
    assembler = BleAssembler()
    assert assembler.feed(b"\x01\x05\x01", 1) == (None, True)
    assert assembler.feed(b"\x00", 1) == (None, False)
    assert assembler.feed(b"\x82\x03abc", 1) == (b"\x05\x01\x03abc", False)
    with pytest.raises(ProtocolError):
        assembler.feed(b"\x82a", 1)
    assert assembler.feed(b"\x81\x09", 1) == (b"\x09", False)


def test_identity_endianness_and_status():
    identity = decode_fields(
        b"\x05\x01\x03v1!\x09\xd3\x48\x0b\x06\x05\x04\x03\x02\x01", True
    )
    assert identity == {
        "firmware": "v1!",
        "super_model": 0x48D3,
        "bluetooth_mac": "01:02:03:04:05:06",
    }
    require_select(identity)
    assert decode_fields(b"\x09\x02\x08\x03\x51") == {
        "print_status_code": 8,
        "print_status": "overheating",
        "battery_percent": 81,
    }


@pytest.mark.parametrize(
    "payload", [b"", b"\x05\x01", b"\x05\x01\x05ab", b"\x05\xff", b"\x05\x09\xd3"]
)
def test_bad_identity_is_not_silently_decoded(payload):
    with pytest.raises(ProtocolError):
        decode_fields(payload, True)


def test_select_required_and_errors_not_treated_as_status():
    for identity in ({}, {"super_model": 0x48D4}):
        with pytest.raises(ProtocolError):
            require_select(identity)
    with pytest.raises(ProtocolError):
        check_response(b"\x08\x03", b"\x01\x08\x0e")


class FakeConnection:
    def __init__(self, reject_setup=False):
        self.requests = []
        self.reject_setup = reject_setup

    async def exchange(self, message):
        validate_request(message)
        self.requests.append(message)
        if message[0] == 10:
            return b"\x0b\xf4\x01\x01"
        if message[0] == 36:
            return b"\x01\x24\x02" if self.reject_setup else b"\x25\xe8\x03\x00"
        if message[0] == 4:
            tag = message[1]
            kind = ATTRIBUTES[tag][1]
            value = b"\xd3\x48" if tag == 9 else b"\x01" * (6 if kind == "mac" else 2)
            if kind == "string":
                value = b"\x03abc"
            return bytes([5, tag]) + value
        return b"\x09\x03\x55\x02\x01"


def test_read_only_transcript_and_private_raw_trace(tmp_path):
    async def exercise():
        path = tmp_path / "trace.jsonl"
        trace = Trace(path)
        for transport in ("ble", "rfcomm"):
            connection = FakeConnection(reject_setup=True)
            setup = await negotiate(connection, transport, trace)
            assert setup["connection_setup"] == "rejected"
            identity, errors = await read_identity(connection)
            require_select(identity)
            assert not errors
            assert (await read_status(connection))["battery_percent"] == 85
            assert {request[0] for request in connection.requests} == {4, 8, 10, 36}
        trace.frame("ble", "tx", b"\x81\x04\x01")
        trace.close()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        records = [json.loads(line) for line in path.read_text().splitlines()]
        assert records[-1]["hex"] == "810401"
        with pytest.raises(FileExistsError):
            Trace(path)

    asyncio.run(exercise())
