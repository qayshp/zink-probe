import asyncio
from argparse import Namespace

import pytest
from test_protocol import FakeConnection

from zink_probe import cli
from zink_probe.protocol import ProtocolError


class Trace:
    def event(self, *args, **kwargs):
        pass


def harness(monkeypatch, model=0x48D3, rfcomm_fails=False):
    connections = []

    class FakeTransport(FakeConnection):
        def __init__(self, *args):
            super().__init__()
            self.closed = False
            self.is_rfcomm = len(connections) == 1
            connections.append(self)

        async def open(self):
            if self.is_rfcomm and rfcomm_fails:
                raise ConnectionError("not paired")

        async def close(self):
            self.closed = True

        def inventory(self):
            return []

        async def exchange(self, request):
            if request == b"\x04\x09":
                return b"\x05\x09" + model.to_bytes(2, "little")
            return await super().exchange(request)

    async def discover(*args):
        return [(object(), {"ble_id": "test-uuid", "select_advertisement": True})]

    monkeypatch.setattr(cli, "discover", discover)
    monkeypatch.setattr(cli, "BleConnection", FakeTransport)
    monkeypatch.setattr(cli, "RfcommConnection", FakeTransport)
    return connections


def args():
    return Namespace(command="probe", ble_id=None, scan_seconds=1, timeout=1)


def test_full_two_transport_probe(monkeypatch):
    connections = harness(monkeypatch)
    result = {"ok": False}
    assert asyncio.run(cli.run(args(), Trace(), result)) == 0
    assert result["ok"]
    assert result["ble"]["status"]["battery_percent"] == 85
    assert result["rfcomm"]["identity"]["firmware"] == "abc"
    assert len(connections) == 2
    assert all(c.closed for c in connections)


def test_extended_probe_reads_configuration_and_preserves_bits(monkeypatch):
    connections = harness(monkeypatch)

    async def sdp_inventory(self):
        return {"fresh": True, "services": []}

    # Both factory bindings reference the same fake class.

    class Classic(cli.RfcommConnection):
        inventory = sdp_inventory

    monkeypatch.setattr(cli, "RfcommConnection", Classic)
    parameters = args()
    parameters.extended = True
    result = {}
    assert asyncio.run(cli.run(parameters, Trace(), result)) == 0
    assert result["rfcomm"]["configuration"]["values"]["led_rgb"] == [1, 1, 1]
    assert result["ble"]["identity"]["first_print_timestamp"] == 0x01010101
    assert result["rfcomm"]["sdp_inventory"]["fresh"] is True
    assert result["ble"]["status_bit_observations"] == {}
    for connection in connections:
        assert {r[0] for r in connection.requests} == {4, 8, 10, 26, 36}


def test_wrong_device_stops_before_rfcomm(monkeypatch):
    connections = harness(monkeypatch, model=0x48D4)
    with pytest.raises(ProtocolError, match="Select identity not confirmed"):
        asyncio.run(cli.run(args(), Trace(), {}))
    assert len(connections) == 1
    assert connections[0].closed


def test_rfcomm_failure_preserves_ble_and_cleans_both(monkeypatch):
    connections = harness(monkeypatch, rfcomm_fails=True)
    result = {"ok": False}
    with pytest.raises(ConnectionError, match="not paired"):
        asyncio.run(cli.run(args(), Trace(), result))
    assert not result["ok"]
    assert result["ble"]["identity"]["super_model"] == 0x48D3
    assert all(c.closed for c in connections)
