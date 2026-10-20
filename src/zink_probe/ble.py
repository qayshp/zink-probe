"""CoreBluetooth through Bleak; requests remain short single-frame messages."""

import asyncio

from .protocol import (
    RX,
    SELECT,
    SERVICE,
    TX,
    BleAssembler,
    ProtocolError,
    validate_request,
)


async def discover(timeout, trace):
    from bleak import BleakScanner

    try:
        found = await asyncio.wait_for(
            BleakScanner.discover(timeout=timeout, return_adv=True), timeout + 15
        )
    except TimeoutError as exc:
        raise TimeoutError(
            "BLE discovery did not finish. Check Bluetooth power and macOS "
            "Privacy & Security > Bluetooth permission for the launching app."
        ) from exc
    candidates = []
    for device, adv in found.values():
        service_data = {
            key.lower(): bytes(value) for key, value in adv.service_data.items()
        }
        raw = service_data.get(SERVICE, b"")
        model = int.from_bytes(raw[:2], "little") if len(raw) >= 2 else None
        name = adv.local_name or device.name or ""
        if (
            model == SELECT
            or "sprocket" in name.lower()
            or SERVICE in adv.service_uuids
        ):
            entry = {
                "ble_id": device.address,
                "name": name,
                "rssi": adv.rssi,
                "super_model": model,
                "select_advertisement": model == SELECT,
                "service_data": {k: v.hex() for k, v in service_data.items()},
            }
            trace.event("discovery", **entry)
            candidates.append((device, entry))
    return candidates


class BleConnection:
    def __init__(self, device, timeout, trace):
        from bleak import BleakClient

        self.client = BleakClient(device, timeout=timeout)
        self.timeout = timeout
        self.trace = trace
        self.assembler = BleAssembler()
        self.ack_period = 0
        self.queue = asyncio.Queue()
        self.ack_tasks = set()
        self.lock = asyncio.Lock()
        self.unsolicited = []
        self.read_handles = set()

    async def open(self):
        await self.client.connect()
        await self.client.start_notify(RX, self._receive)
        self.trace.event("connected", transport="ble")

    def inventory(self):
        # Discovery metadata only: no reads/writes to unknown characteristics.
        return [
            {
                "uuid": service.uuid,
                "description": service.description,
                "characteristics": [
                    {
                        "uuid": char.uuid,
                        "handle": char.handle,
                        "description": char.description,
                        "properties": list(char.properties),
                        "max_write_without_response": char.max_write_without_response_size,
                        "descriptors": [
                            {"uuid": d.uuid, "handle": d.handle}
                            for d in char.descriptors
                        ],
                    }
                    for char in service.characteristics
                ],
            }
            for service in self.client.services
        ]

    async def read_diagnostic_characteristic(self):
        uuid = "6822d239-7b61-4718-bdc1-3dd5acdd2eee"
        self.trace.event("gatt_read_request", transport="ble", uuid=uuid)
        try:
            data = bytes(
                await asyncio.wait_for(self.client.read_gatt_char(uuid), self.timeout)
            )
            result = {"uuid": uuid, "hex": data.hex(), "length": len(data)}
        except Exception as exc:
            result = {"uuid": uuid, "error": f"{type(exc).__name__}: {exc}"}
        self.trace.event("gatt_read_result", transport="ble", **result)
        return result

    def _receive(self, _, data):
        self.trace.frame("ble", "rx", data)
        try:
            message, ack = self.assembler.feed(bytes(data), self.ack_period)
            if ack:
                task = asyncio.create_task(self._ack())
                self.ack_tasks.add(task)
                task.add_done_callback(self.ack_tasks.discard)
            if message is not None:
                self.trace.frame("ble", "rx", message, layer="message")
                if message[:1] == b"\x03":
                    self.unsolicited.append(message.hex())
                    self.trace.event("target_event", transport="ble", hex=message.hex())
                else:
                    self.queue.put_nowait(message)
        except Exception as exc:
            self.queue.put_nowait(exc)

    async def _ack(self):
        try:
            self.trace.frame("ble", "tx", b"\x00")
            await self.client.write_gatt_char(TX, b"\x00", response=True)
        except Exception as exc:
            self.queue.put_nowait(exc)

    async def exchange(self, message):
        validate_request(message, self.read_handles)
        async with self.lock:
            if not self.queue.empty():
                raise ProtocolError(
                    "Unsolicited BLE message before request; refusing ambiguous reply"
                )
            wire = b"\x81" + message
            self.trace.frame("ble", "tx", wire)
            await asyncio.wait_for(
                self.client.write_gatt_char(TX, wire, response=True), self.timeout
            )
            response = await asyncio.wait_for(self.queue.get(), self.timeout)
            if isinstance(response, Exception):
                raise response
            if message == b"\x0a\x01\x00" and response[:1] == b"\x0b":
                if len(response) < 4:
                    raise ProtocolError("Truncated BLE IF_CONFIG reply")
                self.ack_period = response[3]
            return response

    async def close(self):
        tasks = list(self.ack_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.client.disconnect()
        self.trace.event("disconnected", transport="ble")
