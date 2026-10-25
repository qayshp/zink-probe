"""Linux socket lifecycle over real local sockets; no radio or pairing in tests."""

import asyncio
import errno
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from zink_probe.jobs import FramedSession, JobEngine, JobJournal, JobSpec
from zink_probe.jobs.diagnostics import ReadOnlySession, inspect_printer
from zink_probe.jobs.linux import (
    LinuxRfcommStream,
    managed_objects,
    normalize_address,
    select_device,
)
from zink_probe.jobs.linux_probe import main, run_checks
from zink_probe.jobs.simulator import DEVICE_ID, SimulatedPrinter
from zink_probe.protocol import ProtocolError, validate_request

ADDRESS = "00:11:22:33:44:55"
LOCAL = "66:77:88:99:AA:BB"
ROOT = Path(__file__).resolve().parents[1]


def run(coroutine):
    # Linux uses a selector loop. Windows' default proactor intentionally has
    # no add_reader/add_writer; use its socket-capable selector for this facade.
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(coroutine)


class QuietTrace:
    def event(self, *args, **kwargs):
        pass

    def frame(self, *args, **kwargs):
        pass


def objects():
    return {
        "/org/bluez/hci0": {"org.bluez.Adapter1": {"Address": LOCAL, "Powered": True}},
        "/org/bluez/hci0/dev_00_11_22_33_44_55": {
            "org.bluez.Device1": {
                "Address": ADDRESS,
                "AddressType": "public",
                "Paired": True,
                "Blocked": False,
                "Adapter": "/org/bluez/hci0",
            }
        },
    }


class SocketFacade:
    """Only bind/connect are synthetic. Read/write/readiness use a real socket."""

    def __init__(self, sock):
        self.sock = sock
        self.connect_code = 0
        self.socket_error = 0
        self.send_limit, self.recv_limit = 19, 11
        self.send_blocks = 0
        self.send_failure_after = None
        self.sent = bytearray()
        self.closed = self.connects = self.send_attempts = 0
        self.bind_address = None

    def setblocking(self, value):
        self.sock.setblocking(value)

    def bind(self, address):
        self.bind_address = address

    def connect_ex(self, address):
        assert address == (ADDRESS, 2)
        self.connects += 1
        return self.connect_code

    def getsockopt(self, level, option):
        assert (level, option) == (socket.SOL_SOCKET, socket.SO_ERROR)
        return self.socket_error

    def fileno(self):
        return self.sock.fileno()

    def send(self, data):
        self.send_attempts += 1
        if self.send_blocks:
            self.send_blocks -= 1
            raise BlockingIOError(errno.EAGAIN, "try when writable")
        if (
            self.send_failure_after is not None
            and len(self.sent) >= self.send_failure_after
        ):
            raise BrokenPipeError(errno.EPIPE, "failure after partial write")
        sent = self.sock.send(data[: self.send_limit])
        self.sent.extend(data[:sent])
        return sent

    def recv(self, maximum):
        return self.sock.recv(min(maximum, self.recv_limit))

    def close(self):
        self.closed += 1
        self.sock.close()


class Harness:
    def __init__(self, peer=None):
        client, self.server = socket.socketpair()
        self.server.setblocking(False)
        self.facade = SocketFacade(client)
        self.peer = peer or SimulatedPrinter()
        self.task = None
        self.inspections = 0
        self.inspection_error = None

    async def inspect(self, address, adapter):
        self.inspections += 1
        if self.inspection_error:
            raise self.inspection_error
        return select_device(objects(), address, adapter)

    def stream(self, **kwargs):
        return LinuxRfcommStream(
            ADDRESS,
            _socket_factory=lambda: self.facade,
            _inspect=self.inspect,
            **kwargs,
        )

    def start(self):
        self.task = asyncio.create_task(self.serve())

    async def serve(self):
        loop = asyncio.get_running_loop()
        while data := await loop.sock_recv(self.server, 73):
            await self.peer.write(data)
            while self.peer.response_bytes:
                data = bytes(self.peer.response_bytes[:17])
                del self.peer.response_bytes[:17]
                await loop.sock_sendall(self.server, data)

    async def finish(self):
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.server.close()
        if self.facade.sock.fileno() >= 0:
            self.facade.close()


def test_normalization_and_parameters():
    assert normalize_address("aa-bb-cc-dd-ee-ff") == "AA:BB:CC:DD:EE:FF"
    for bad in (None, "BLE-UUID", "aa:bb-cc:dd:ee:ff", "aabbccddeeff"):
        with pytest.raises(ValueError):
            LinuxRfcommStream(bad)
    for options in (
        {"adapter": "hci0;cmd"},
        {"timeout": 0},
        {"timeout": float("nan")},
        {"timeout": float("inf")},
        {"write_chunk_size": 0},
        {"write_chunk_size": True},
    ):
        with pytest.raises(ValueError):
            LinuxRfcommStream(ADDRESS, **options)


@pytest.mark.parametrize(
    "change,match",
    [
        ("missing", "not known"),
        ("unpaired", "not paired"),
        ("blocked", "blocked"),
        ("powered-off", "not powered"),
        ("random", "public"),
        ("ambiguous", "multiple adapters"),
        ("bad-parent", "adapter reference"),
        ("missing-blocked", "blocked state"),
    ],
)
def test_bluez_preflight_selection(change, match):
    data = objects()
    adapter = data["/org/bluez/hci0"]["org.bluez.Adapter1"]
    device = data["/org/bluez/hci0/dev_00_11_22_33_44_55"]["org.bluez.Device1"]
    if change == "missing":
        data.clear()
    elif change == "unpaired":
        device["Paired"] = False
    elif change == "blocked":
        device["Blocked"] = True
    elif change == "powered-off":
        adapter["Powered"] = False
    elif change == "random":
        device["AddressType"] = "random"
    elif change == "bad-parent":
        device["Adapter"] = "/elsewhere/hci0"
    elif change == "missing-blocked":
        device.pop("Blocked")
    else:
        data["/org/bluez/hci1"] = {"org.bluez.Adapter1": dict(adapter)}
        data["/org/bluez/hci1/dev_00_11_22_33_44_55"] = {
            "org.bluez.Device1": dict(device, Adapter="/org/bluez/hci1")
        }
        assert select_device(data, ADDRESS, "hci0")["adapter"] == "hci0"
    with pytest.raises(ConnectionError, match=match):
        select_device(data, ADDRESS)


def test_fragmented_stream_and_inprogress_connect():
    async def case():
        h = Harness()
        h.facade.connect_code = errno.EINPROGRESS
        h.facade.send_blocks = 1
        h.start()
        stream = h.stream()
        await stream.open()
        assert h.facade.bind_address == (LOCAL, 0)
        session = ReadOnlySession(stream)
        assert await session.exchange(b"\x0a\x02") == b"\x0b\x00"
        assert session.events and stream.native_writes >= 2
        assert stream.tx_bytes == len(h.facade.sent) and stream.rx_bytes > 0
        await session.close()
        await stream.close()
        assert stream.state == "closed" and not stream._waiters
        assert h.facade.closed == 1 and h.facade.connects == 1
        with pytest.raises(RuntimeError, match="single-use"):
            await stream.open()
        await h.finish()

    run(case())


@pytest.mark.parametrize("pending", [False, True])
def test_connect_error_closes_and_releases_lease(pending):
    async def case():
        h = Harness()
        h.facade.connect_code = errno.EINPROGRESS if pending else errno.EACCES
        h.facade.socket_error = errno.EACCES
        stream = h.stream()
        with pytest.raises(OSError, match="permissions"):
            await stream.open()
        assert stream.state == "closed" and h.facade.closed == 1
        assert not stream._waiters and not h.facade.sent
        await h.finish()

    run(case())


def test_preflight_failure_never_creates_socket():
    async def case():
        h = Harness()
        h.inspection_error = ConnectionError("not paired")
        stream = h.stream()
        with pytest.raises(ConnectionError, match="not paired"):
            await stream.open()
        assert h.facade.connects == h.facade.closed == 0
        assert stream.state == "closed"
        await h.finish()

    run(case())


@pytest.mark.parametrize("phase", ["preflight", "connect", "read"])
def test_deadlines_close_owned_resources(phase):
    async def case():
        h = Harness()
        stream = h.stream(timeout=0.03)

        async def hang(*args):
            await asyncio.Event().wait()

        if phase == "preflight":
            stream._inspect = hang
        elif phase == "connect":
            h.facade.connect_code = errno.EINPROGRESS
            stream._ready = hang
        else:
            await stream.open()
        with pytest.raises(TimeoutError):
            if phase == "read":
                await stream.read(10)
            else:
                await stream.open()
        assert stream.state == "closed" and not stream._waiters
        assert h.facade.closed == (0 if phase == "preflight" else 1)
        await h.finish()

    run(case())


@pytest.mark.parametrize("action", ["cancel", "close", "peer-eof"])
def test_pending_read_cleanup(action):
    async def case():
        h = Harness()
        stream = h.stream()
        await stream.open()
        task = asyncio.create_task(stream.read(10))
        await asyncio.sleep(0)
        assert stream._waiters
        if action == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif action == "close":
            await stream.close()
            with pytest.raises(ConnectionError):
                await task
        else:
            h.server.close()
            assert await task == b""
        assert stream.state == "closed" and not stream._waiters
        assert h.facade.closed == 1
        await h.finish()

    run(case())


def test_partial_write_error_never_resends_prefix():
    async def case():
        h = Harness()
        h.facade.send_failure_after = 19
        stream = h.stream()
        await stream.open()
        with pytest.raises(BrokenPipeError):
            await stream.write(bytes(range(100)))
        assert bytes(h.facade.sent) == bytes(range(19))
        assert stream.tx_bytes == 19 and stream.state == "closed"
        with pytest.raises(ConnectionError):
            await stream.write(b"retry")
        assert h.facade.connects == 1 and h.facade.closed == 1
        await h.finish()

    run(case())


@pytest.mark.parametrize("cancel", [False, True])
def test_real_socket_backpressure_timeout_or_cancel(cancel):
    async def case():
        h = Harness()
        stream = h.stream(timeout=0.1)
        await stream.open()
        h.facade.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        while True:
            try:
                h.facade.sock.send(b"x" * 4096)
            except BlockingIOError:
                break
        task = asyncio.create_task(stream.write(b"blocked"))
        await asyncio.sleep(0)
        assert stream._waiters
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
            await task
        assert not stream._waiters and stream.state == "closed"
        assert stream.tx_bytes == 0
        await h.finish()

    run(case())


def test_second_owner_cannot_release_first_lease():
    async def case():
        h, other = Harness(), Harness()
        first, second = h.stream(), other.stream()
        await first.open()
        for candidate in (second, other.stream()):
            with pytest.raises(ConnectionError, match="active Linux stream"):
                await candidate.open()
        assert first.state == "open" and h.facade.closed == 0
        await first.close()
        fresh = other.stream()
        await fresh.open()
        await fresh.close()
        await h.finish()
        await other.finish()

    run(case())


@pytest.mark.parametrize(
    "filename,alternative",
    [
        ("experiments/calibration/package-v2/python.jpg", False),
        ("experiments/jpeg-quality/q100-444-optimized.jpg", True),
    ],
)
def test_full_job_over_real_socket_facade(tmp_path, filename, alternative):
    async def case():
        h = Harness()
        h.start()
        stream = h.stream()
        await stream.open()
        payload = (ROOT / filename).read_bytes()
        job = JobSpec(payload, name="LINUX-SIM", allow_alternative_sampling=alternative)
        with JobJournal(tmp_path / "jobs.sqlite") as journal:
            result = await JobEngine(
                FramedSession(stream),
                journal,
                DEVICE_ID,
                poll_interval=0,
                observation_timeout=10,
            ).run(job)
        assert result.state == "completed", result
        assert not result.physical_ejection_confirmed
        assert bytes(h.peer.uploaded) == payload
        assert sum(r[0] == 12 for r in h.peer.mutations) == 1
        assert h.facade.closed == 1 and stream.state == "closed"
        await h.finish()

    run(case())


def test_missing_printstart_reply_is_uncertain_without_retry(tmp_path):
    async def case():
        h = Harness(
            SimulatedPrinter(
                fault=lambda req, reply, peer: None if req[0] == 12 else reply
            )
        )
        h.start()
        stream = h.stream()
        await stream.open()
        job = JobSpec(
            (ROOT / "experiments/calibration/package-v2/python.jpg").read_bytes()
        )
        with JobJournal(tmp_path / "jobs.sqlite") as journal:
            result = await JobEngine(
                FramedSession(stream, timeout=0.1), journal, DEVICE_ID, poll_interval=0
            ).run(job)
            assert result.state == "uncertain"
            assert journal.get(job.local_id)["pending"]["opcode"] == 12
        assert sum(r[0] == 12 for r in h.peer.mutations) == 1
        assert not h.peer.uploaded and h.facade.closed == 1
        await h.finish()

    run(case())


@pytest.mark.parametrize(
    "payload",
    [
        b"\x0c\x01\x01\x00\x00\x00",
        b"\x0e\x07x",
        b"\x30\x01\x00",
        b"\x1c\x01\x00",
        b"\x28\x09\x01",
    ],
)
def test_read_only_gate_prevents_job_or_unscoped_file_requests(payload):
    async def case():
        h = Harness()
        stream = h.stream()
        await stream.open()
        session = ReadOnlySession(stream)
        with pytest.raises(ProtocolError, match="allowlist"):
            await session.exchange(payload)
        assert not h.facade.sent
        await session.close()
        await h.finish()

    run(case())


def test_two_read_only_sessions_and_wrong_identity():
    async def case():
        harnesses = []

        def factory(address, **kwargs):
            h = Harness()
            h.start()
            harnesses.append(h)
            return h.stream(**kwargs)

        args = SimpleNamespace(
            address=ADDRESS,
            adapter="hci0",
            device_id=DEVICE_ID,
            sessions=2,
            timeout=10,
            session_timeout=30,
        )
        results = await run_checks(args, QuietTrace(), stream_factory=factory)
        for result, h in zip(results, harnesses):
            assert result["configuration_unchanged"] and result["counters_unchanged"]
            assert result["transport"]["closed"] and not h.peer.mutations
            for request in h.peer.requests:
                validate_request(request, read_handles={9} if request[0] == 40 else ())
            await h.finish()
        h = Harness()
        h.start()
        stream = h.stream()
        await stream.open()
        with pytest.raises(ProtocolError, match="identity"):
            await inspect_printer(ReadOnlySession(stream), "ff" * 16, QuietTrace())
        assert {r[0] for r in h.peer.requests} <= {4, 10, 36}
        await stream.close()
        await h.finish()

    run(case())


def test_sequence_stops_at_first_failure():
    async def case():
        calls = []

        def factory(address, **kwargs):
            h = Harness()
            h.inspection_error = ConnectionError("unpaired")
            calls.append(h)
            return h.stream(**kwargs)

        args = SimpleNamespace(
            address=ADDRESS,
            adapter=None,
            device_id=DEVICE_ID,
            sessions=3,
            timeout=10,
            session_timeout=30,
        )
        with pytest.raises(ConnectionError, match="unpaired"):
            await run_checks(args, QuietTrace(), stream_factory=factory)
        assert len(calls) == 1 and not calls[0].facade.sent
        await calls[0].finish()

    run(case())


def test_lazy_imports_and_no_print_option():
    code = """
import sys
class ForbidNative:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'dbus_fast', 'objc', 'IOBluetooth', 'bleak', 'PIL'}:
            raise AssertionError(fullname)
sys.meta_path.insert(0, ForbidNative())
import zink_probe.jobs.linux
import zink_probe.jobs.linux_probe
"""
    subprocess.run([sys.executable, "-I", "-c", code], check=True, capture_output=True)
    with pytest.raises(SystemExit) as exc:
        main(["--address", ADDRESS, "--device-id", DEVICE_ID, "--print"])
    assert exc.value.code == 2


@pytest.mark.parametrize(
    "failure", [None, "connect", "call", "error-reply", "signature", "cancel"]
)
def test_bluez_reads_only_object_manager_and_disconnects(monkeypatch, failure):
    calls = []
    buses = []

    class Bus:
        def __init__(self, **kwargs):
            assert kwargs == {"bus_type": "system"}
            self.closed = False
            buses.append(self)

        async def connect(self):
            if failure == "connect":
                raise ConnectionError("no system bus")
            return self

        async def call(self, message):
            calls.append(message)
            if failure == "call":
                raise ConnectionError("lost system bus")
            if failure == "cancel":
                raise asyncio.CancelledError()
            return SimpleNamespace(
                message_type="error" if failure == "error-reply" else "reply",
                error_name="org.bluez.NotReady",
                signature="wrong" if failure == "signature" else "a{oa{sa{sv}}}",
                body=[
                    {
                        path: {
                            iface: {
                                key: SimpleNamespace(value=value)
                                for key, value in props.items()
                            }
                            for iface, props in interfaces.items()
                        }
                        for path, interfaces in objects().items()
                    }
                ],
            )

        def disconnect(self):
            self.closed = True

        async def wait_for_disconnect(self):
            assert self.closed

    # No real D-Bus module/socket is imported. Native API smoke tests run on Linux.
    monkeypatch.setitem(
        sys.modules,
        "dbus_fast",
        SimpleNamespace(
            BusType=SimpleNamespace(SYSTEM="system"),
            Message=SimpleNamespace,
            MessageType=SimpleNamespace(ERROR="error"),
        ),
    )
    monkeypatch.setitem(sys.modules, "dbus_fast.aio", SimpleNamespace(MessageBus=Bus))
    monkeypatch.setattr("zink_probe.jobs.linux.sys.platform", "linux")

    async def case():
        if failure:
            with pytest.raises(
                asyncio.CancelledError if failure == "cancel" else ConnectionError
            ):
                await managed_objects()
        else:
            assert await managed_objects() == objects()
        assert buses[0].closed
        for call in calls:
            assert vars(call) == dict(
                destination="org.bluez",
                path="/",
                interface="org.freedesktop.DBus.ObjectManager",
                member="GetManagedObjects",
            )

    run(case())


def test_native_linux_dbus_message_without_bus_or_bluetooth():
    if sys.platform != "linux":
        pytest.skip("Linux native dependency smoke check")
    dbus = pytest.importorskip("dbus_fast")
    assert socket.AF_BLUETOOTH and socket.BTPROTO_RFCOMM
    message = dbus.Message(
        destination="org.bluez",
        path="/",
        interface="org.freedesktop.DBus.ObjectManager",
        member="GetManagedObjects",
    )
    assert message.signature == "" and message.body == []
