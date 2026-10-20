import asyncio

import pytest

from zink_probe.capabilities import (
    decode_feature_table,
    read_capabilities,
    read_metrics,
)
from zink_probe.protocol import ProtocolError, decode_fields, validate_request


def test_tlv_feature_table_and_unknown_field():
    data = b"\x01\x02\x00\x09\x00\x03\x03\x00\x02\x04\x08\x63\x01\x00\xaa"
    assert decode_feature_table(data, 2) == {
        "version": 9,
        "requests": [4, 8],
        "unknown_0x63": "aa",
    }
    for bad in (b"\x01", b"\x01\x02\x00\x00", b"\x03\x02\x00\x04\x08"):
        with pytest.raises(ProtocolError):
            decode_feature_table(bad, 2)


def test_file_reads_require_scoped_handle_and_cannot_write_or_update():
    for request in (
        b"\x28\x07\x01",
        b"\x0e\x07\x01",
        b"\x10\x01",
        b"\x12\x01",
        b"\x38\x01",
    ):
        with pytest.raises(ProtocolError):
            validate_request(request)
    validate_request(b"\x28\x07\x01", {7})
    for request in (b"\x28\x07\x03", b"\x28\x08\x01"):
        with pytest.raises(ProtocolError):
            validate_request(request, {7})


def test_feature_download_scopes_and_releases_handle():
    class Connection:
        read_handles = set()

        async def exchange(self, request):
            validate_request(request, self.read_handles)
            if request == b"\x2a":
                return b"\x2b\x07\x02"
            return b"\x29\x07\x00\x00\x00\x00\x01\x02\x00\x09\x00"

    connection = Connection()
    result = asyncio.run(read_capabilities(connection))
    assert result["table"] == {"version": 9}
    assert not connection.read_handles


def test_metrics_follows_returned_iterator_and_decodes_keys():
    class Connection:
        async def exchange(self, request):
            validate_request(request)
            if request == b"\x3a\x01\x00\x00":
                return b"\x3b\x01\x00\x80\x01\x00\x0a\x00\x00\x00"
            assert request == b"\x3a\x01\x00\x80"
            return b"\x3b\x01\x00\x00"

    assert asyncio.run(read_metrics(Connection()))["values"] == {
        "1": {"name": "printer_pages", "value": 10}
    }


def test_source_backed_status_labels_and_raw_values():
    result = decode_fields(b"\x09\x01\x01\x00\x00\x00\x06\x02\x07\x01")
    assert result["battery_status"] == "charging"
    assert result["queue_status"] == "empty"
    assert result["system_flag_labels"] == ["time_invalid"]
    assert result["system_flags"] == 1
    assert result["system_flags_unknown_mask"] == 0


def test_long_strings_use_varint_length_not_one_byte():
    name = b"x" * 128
    assert decode_fields(b"\x05\x04\x80\x01" + name, True)["custom_name"] == "x" * 128
    with pytest.raises(ProtocolError):
        decode_fields(b"\x05\x04\x80", True)


def test_passive_channel_never_writes():
    from zink_probe.rfcomm import RfcommConnection

    connection = RfcommConnection.__new__(RfcommConnection)
    connection.channel_id = 1
    with pytest.raises(ProtocolError, match="receive-only"):
        asyncio.run(connection.exchange(b"\x08\x03"))


def test_feature_handle_released_after_bad_reply():
    class Connection:
        read_handles = set()

        async def exchange(self, request):
            if request == b"\x2a":
                return b"\x2b\x07\x02"
            return b"\x29\x08\x00\x00\x00\x00"  # Mismatched handle.

    connection = Connection()
    with pytest.raises(ProtocolError):
        asyncio.run(read_capabilities(connection))
    assert not connection.read_handles


def test_metrics_repeated_iterator_fails_instead_of_looping():
    class Connection:
        async def exchange(self, request):
            return b"\x3b\x01\x01\x00"

    with pytest.raises(ProtocolError, match="Repeated metrics iterator"):
        asyncio.run(read_metrics(Connection()))


def test_physical_select_capability_table_without_device_identifiers():
    data = bytes.fromhex(
        "01020009000202000100031c001b0406080a0c0e10121416181a1c20222426282a2c2e30323436383a040500040102030405"
        "02000101060200010107020001010805000401020304090100000a06000501020304050b03000201020c0f000e0102030405"
        "060708090a0b0c0d0e0d080007010203050607090e0100000f130006ffffff002ee03f006fff348b967d0000840010130006"
        "dafffe0076eb9e4cf7ff64fbfbff660ee6791102000101120700060102030506081302002000140200100015030001020016"
        "020000001702000101180900020000000001000000190300020001"
    )
    result = decode_feature_table(data, 2)
    assert len(data) == 227
    assert result["version"] == 9 and result["proto_version"] == 1
    assert len(result["requests"]) == 27
    assert result["status"] == [1, 2, 3, 5, 6, 7, 9]
    assert result["color_palette"][0] == "#ffffff"
    assert result["custom_name_max"] == 32
    assert result["metrics_db"] == [1]
