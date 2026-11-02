import asyncio

import pytest

from zink_probe.ble import BleConnection
from zink_probe.protocol import ProtocolError


def exchange_config(reply):
    async def run():
        connection = BleConnection.__new__(BleConnection)
        connection.read_handles = set()
        connection.config_writes = set()
        connection.timeout = 1
        connection.lock = asyncio.Lock()
        connection.queue = asyncio.Queue()
        connection.ack_period = 0

        class Client:
            async def write_gatt_char(self, uuid, wire, response):
                assert wire == bytes.fromhex("810a0100")
                connection.queue.put_nowait(reply)

        class Trace:
            def frame(self, *args, **kwargs):
                pass

        connection.client = Client()
        connection.trace = Trace()
        await connection.exchange(bytes.fromhex("0a0100"))
        return connection.ack_period

    return asyncio.run(run())


def test_observed_ble_config_does_not_confuse_mtu_high_byte_with_ack():
    # Observed Select reply: interface 1, protocol MTU 514, ACK period 0.
    assert exchange_config(bytes.fromhex("0b01020200")) == 0
    # Different MTU and nonzero ACK period must also be independent.
    assert exchange_config(bytes.fromhex("0b01140003")) == 3


@pytest.mark.parametrize("reply", ["0b010202", "0b02020200", "0b0102020000"])
def test_invalid_ble_config_stops_exchange(reply):
    with pytest.raises(ProtocolError, match="Invalid BLE IF_CONFIG"):
        exchange_config(bytes.fromhex(reply))
