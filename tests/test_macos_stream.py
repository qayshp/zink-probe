"""Native callback boundary exercised without a radio, on every CI platform."""

import asyncio
import subprocess
import sys
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest

from zink_probe.jobs import FramedSession, JobEngine, JobJournal, JobSpec
from zink_probe.jobs.diagnostics import ReadOnlySession, inspect_printer
from zink_probe.jobs.macos import MacOSRfcommStream, normalize_address
from zink_probe.jobs.macos_probe import main, run_checks
from zink_probe.jobs.simulator import DEVICE_ID, SimulatedPrinter
from zink_probe.jobs.transport import frame
from zink_probe.protocol import ProtocolError, validate_request

ADDRESS = "00:11:22:33:44:55"
ROOT = Path(__file__).resolve().parents[1]


class QuietTrace:
    def event(self, *args, **kwargs):
        pass

    def frame(self, *args, **kwargs):
        pass


class FakeBackend:
    """A Cocoa-pumped native facade; the peer behind it is still a simulator."""

    def __init__(self, peer=None, *, mtu=47, open_rc=0, open_status=0, paired=True):
        self.peer = peer or SimulatedPrinter()
        self.mtu, self.open_rc, self.open_status = mtu, open_rc, open_status
        self.paired = paired
        self.owner = self.channel = None
        self.callbacks = deque()
        self.tasks = []
        self.pumps = 0
        self.write_rc = self.write_status = self.close_rc = 0
        self.omit_write_callback = False
        self.omit_close_callback = False
        self.disconnect_on_write = False
        self.pump_error = None
        self.fragments = []

    def device(self, address):
        assert address == "00-11-22-33-44-55"
        return self

    def isPaired(self):
        return self.paired

    def delegate(self, owner):
        self.owner = owner
        return SimpleNamespace(owner=owner)

    def openRFCOMMChannelAsync_withChannelID_delegate_(self, unused, channel, delegate):
        assert unused is None and channel == 2 and delegate.owner is self.owner
        self.channel = FakeChannel(self)
        if self.open_status is not None:
            self.callbacks.append(lambda: self.owner._opened(self.open_status))
        return self.open_rc, self.channel

    def pump(self):
        self.pumps += 1
        if self.pump_error:
            raise self.pump_error
        while self.callbacks:
            self.callbacks.popleft()()

    async def dispatch(self, data):
        await self.peer.write(data)
        if self.disconnect_on_write:
            self.callbacks.append(self.owner._disconnected)
            return
        # Data can arrive before the native write completion notification.
        while self.peer.response_bytes:
            chunk = bytes(self.peer.response_bytes[:13])
            del self.peer.response_bytes[:13]
            self.callbacks.append(lambda chunk=chunk: self.owner._received(chunk))
        if not self.omit_write_callback:
            self.callbacks.append(lambda: self.owner._written(self.write_status))


class FakeChannel:
    def __init__(self, backend):
        self.backend = backend
        self.closed = 0
        self.detached = False

    def isOpen(self):
        return self.backend.open_status == 0 and not self.closed

    def getMTU(self):
        return self.backend.mtu

    def writeAsync_length_refcon_(self, data, length, refcon):
        b = self.backend
        assert isinstance(data, bytes) and len(data) == length <= b.mtu
        assert refcon is None and not self.closed
        b.fragments.append(data)
        if not b.write_rc:
            b.tasks.append(asyncio.create_task(b.dispatch(data)))
        return b.write_rc

    def setDelegate_(self, delegate):
        assert delegate is None
        self.detached = True

    def closeChannel(self):
        self.closed += 1
        if not self.backend.omit_close_callback:
            self.backend.callbacks.append(self.backend.owner._disconnected)
        return self.backend.close_rc


def make_stream(backend=None, **kwargs):
    return MacOSRfcommStream(ADDRESS, _backend=backend or FakeBackend(), **kwargs)


def test_address_and_constructor_validation():
    assert normalize_address("AA:BB:CC:DD:EE:FF") == "aa-bb-cc-dd-ee-ff"
    for bad in ("BLE-UUID", "aabbccddeeff", "00:11-22:33:44:55", None):
        with pytest.raises(ValueError):
            normalize_address(bad)
    for timeout in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            make_stream(timeout=timeout)
    with pytest.raises(ValueError):
        make_stream(receive_limit=10)


def test_fragmented_reads_events_and_owned_channel_cleanup():
    async def case():
        backend = FakeBackend(mtu=3)
        stream = make_stream(backend)
        await stream.open()
        session = ReadOnlySession(stream)
        assert await session.exchange(b"\x0a\x02") == b"\x0b\x00"
        assert session.events and len(backend.fragments) == 3
        assert b"".join(backend.fragments) == frame(b"\x0a\x02")
        stream._received(b"abcdef")
        assert await stream.read(2) == b"ab"
        assert await stream.read(100) == b"cdef"
        stream._disconnected()
        assert await stream.read(1) == b""
        await session.close()
        await stream.close()
        assert backend.channel.closed == 1 and backend.channel.detached
        assert stream._pump_task is None and stream._delegate is None
        with pytest.raises(RuntimeError, match="single-use"):
            await stream.open()

    asyncio.run(case())


def test_local_close_waits_for_callback_and_reports_unconfirmed_teardown():
    async def case():
        b = FakeBackend()
        stream = make_stream(b)
        await stream.open()
        await stream.close()
        assert stream._close_ready.is_set() and stream.close_error is None
        missing = FakeBackend()
        missing.omit_close_callback = True
        other = make_stream(missing)
        await other.open()
        other.timeout = 0.01
        await other.close()
        assert "close callback" in other.close_error
        assert other.state == "closed" and other._pump_task is None
        assert missing.channel.detached

    asyncio.run(case())


def test_duplicate_adapter_cannot_steal_an_active_native_channel():
    async def case():
        first_backend, second_backend = FakeBackend(), FakeBackend()
        first, second = make_stream(first_backend), make_stream(second_backend)
        await first.open()
        with pytest.raises(ConnectionError, match="Another adapter stream"):
            await second.open()
        assert second_backend.channel is None
        assert first.state == "open" and first_backend.channel.closed == 0
        await first.close()
        third = make_stream()
        await third.open()
        await third.close()

    asyncio.run(case())


@pytest.mark.parametrize(
    "mode", ["unpaired", "open_return", "open_callback", "open_timeout", "mtu", "pump"]
)
def test_open_failures_cleanup_without_transmitting(mode):
    async def case():
        b = FakeBackend()
        if mode == "unpaired":
            b.paired = False
        if mode == "open_return":
            b.open_rc = 99
        if mode == "open_callback":
            b.open_status = 99
        if mode == "open_timeout":
            b.open_status = None
        if mode == "mtu":
            b.mtu = 0
        if mode == "pump":
            b.pump_error = RuntimeError("pump broke")
        stream = make_stream(b, timeout=0.05)
        with pytest.raises((ConnectionError, TimeoutError)):
            await stream.open()
        assert stream.state == "closed" and stream._pump_task is None
        assert not b.fragments
        if b.channel:
            assert b.channel.closed == 1 and b.channel.detached
        # A late native callback cannot reopen a timed-out stream.
        stream._opened(0)
        assert stream.state == "closed"

    asyncio.run(case())


@pytest.mark.parametrize("mode", ["return", "callback", "timeout", "disconnect"])
def test_write_faults_close_and_never_resend(mode):
    async def case():
        b = FakeBackend(mtu=4096)
        stream = make_stream(b)
        await stream.open()
        stream.timeout = 0.05
        if mode == "return":
            b.write_rc = 99
        if mode == "callback":
            b.write_status = 99
        if mode == "timeout":
            b.omit_write_callback = True
        if mode == "disconnect":
            b.disconnect_on_write = True
        with pytest.raises((ConnectionError, TimeoutError)):
            await stream.write(frame(b"\x0a\x02"))
        assert stream.state == "closed" and len(b.fragments) == 1
        with pytest.raises(ConnectionError):
            await stream.write(frame(b"\x0a\x02"))
        assert len(b.fragments) == 1 and b.channel.closed == 1

    asyncio.run(case())


@pytest.mark.parametrize("operation", ["open", "read", "write"])
def test_cancellation_closes_channel_and_pump(operation):
    async def case():
        b = FakeBackend(open_status=None if operation == "open" else 0)
        stream = make_stream(b)
        if operation != "open":
            await stream.open()
        b.omit_write_callback = True
        task = asyncio.create_task(
            stream.open()
            if operation == "open"
            else stream.read(10)
            if operation == "read"
            else stream.write(frame(b"\x0a\x02"))
        )
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.state == "closed" and stream._pump_task is None
        assert b.channel.closed == 1 and b.channel.detached
        for pending in b.tasks:
            await pending

    asyncio.run(case())


def test_read_timeout_overflow_close_error_and_thread_affinity():
    async def case():
        b = FakeBackend()
        stream = make_stream(b, receive_limit=4102)
        await stream.open()
        with pytest.raises(RuntimeError, match="main thread"):
            await asyncio.to_thread(lambda: asyncio.run(stream.read(1)))
        for size in (0, -1, True):
            with pytest.raises(ValueError):
                await stream.read(size)
        stream._received(bytes(4103))
        with pytest.raises(ConnectionError, match="buffer"):
            await stream.read(1)
        assert stream.state == "closed" and not stream._buffer
        other = make_stream()
        await other.open()
        other.timeout = 0.01
        with pytest.raises(TimeoutError):
            await other.read(1)
        assert other.state == "closed"
        failing = FakeBackend()
        last = make_stream(failing)
        await last.open()
        failing.close_rc = 99
        await last.close()
        assert "99" in last.close_error

    asyncio.run(case())


def test_owning_event_loop_is_enforced():
    stream = make_stream()

    async def first():
        await stream.open()
        await stream.close()

    asyncio.run(first())
    with pytest.raises(RuntimeError, match="another asyncio loop"):
        asyncio.run(stream.read(1))


@pytest.mark.parametrize(
    "payload",
    [
        b"\x0c\x01\x01\x00\x00\x00",
        b"\x0e\x01jpeg",
        b"\x30\x01",
        b"\x1c\x01\x00",
        b"\x28\x09\x01",
    ],
)
def test_read_only_gate_rejects_before_native_write(payload):
    async def case():
        b = FakeBackend()
        stream = make_stream(b)
        await stream.open()
        session = ReadOnlySession(stream)
        with pytest.raises(ProtocolError, match="allowlist"):
            await session.exchange(payload)
        assert not b.fragments and not b.peer.requests
        await session.close()

    asyncio.run(case())


def test_two_read_only_sessions_use_fresh_channels_and_scoped_handles():
    async def case():
        backends = []

        def factory(address, **kwargs):
            b = FakeBackend()
            backends.append(b)
            return MacOSRfcommStream(address, _backend=b, **kwargs)

        args = SimpleNamespace(
            address=ADDRESS,
            device_id=DEVICE_ID,
            sessions=2,
            timeout=10,
            session_timeout=30,
        )
        results = await run_checks(args, QuietTrace(), stream_factory=factory)
        assert len(results) == len(backends) == 2
        for result, b in zip(results, backends):
            assert result["counters_unchanged"] and result["configuration_unchanged"]
            assert result["transport"]["closed"] and b.channel.closed == 1
            assert result["capabilities"]["table"]["job_name_max"] == 16
            assert not b.peer.mutations
            for req in b.peer.requests:
                validate_request(req, read_handles={9} if req[0] == 40 else ())

    asyncio.run(case())


def test_wrong_identity_stops_before_capabilities_or_jobs():
    async def case():
        b = FakeBackend()
        stream = make_stream(b)
        await stream.open()
        session = ReadOnlySession(stream)
        with pytest.raises(ProtocolError, match="identity"):
            await inspect_printer(session, "ff" * 16, QuietTrace())
        assert {r[0] for r in b.peer.requests} <= {4, 10, 36}
        await session.close()

    asyncio.run(case())


def test_check_stops_at_first_connection_failure():
    async def case():
        backends = []

        def factory(address, **kwargs):
            backend = FakeBackend(open_rc=99)
            backends.append(backend)
            return MacOSRfcommStream(address, _backend=backend, **kwargs)

        args = SimpleNamespace(
            address=ADDRESS,
            device_id=DEVICE_ID,
            sessions=3,
            timeout=10,
            session_timeout=30,
        )
        with pytest.raises(ConnectionError):
            await run_checks(args, QuietTrace(), stream_factory=factory)
        assert len(backends) == 1 and not backends[0].fragments

    asyncio.run(case())


@pytest.mark.parametrize(
    "filename,alternative",
    [
        ("experiments/calibration/package-v2/python.jpg", False),
        ("experiments/jpeg-quality/q100-444-optimized.jpg", True),
    ],
)
def test_full_engine_job_through_native_facade(tmp_path, filename, alternative):
    async def case():
        # The largest frame crosses this MTU. Neither fake nor real stream may
        # treat native fragment boundaries as HP+ message boundaries.
        b = FakeBackend(mtu=509)
        stream = make_stream(b)
        await stream.open()
        data = (ROOT / filename).read_bytes()
        job = JobSpec(data, name="Adapter test", allow_alternative_sampling=alternative)
        with JobJournal(tmp_path / "jobs.sqlite") as journal:
            result = await JobEngine(
                FramedSession(stream),
                journal,
                DEVICE_ID,
                poll_interval=0,
                observation_timeout=10,
            ).run(job)
        assert result.state == "completed", result
        assert bytes(b.peer.uploaded) == data
        assert sum(r[0] == 12 for r in b.peer.mutations) == 1
        assert not result.physical_ejection_confirmed
        assert stream.state == "closed" and b.channel.closed == 1
        assert max(map(len, b.fragments)) == 509

    asyncio.run(case())


def test_engine_missing_ack_through_adapter_is_uncertain_without_retry(tmp_path):
    async def case():
        peer = SimulatedPrinter(
            fault=lambda req, reply, p: None if req[0] == 12 else reply
        )
        b = FakeBackend(peer)
        stream = make_stream(b)
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
        assert sum(r[0] == 12 for r in peer.mutations) == 1
        assert not peer.uploaded and stream.state == "closed"

    asyncio.run(case())


def test_modules_import_without_native_dependencies_and_cli_has_no_print_flag():
    code = """
import sys
class ForbidNative:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'objc','Foundation','IOBluetooth','bleak'}:
            raise AssertionError(fullname)
sys.meta_path.insert(0,ForbidNative())
import zink_probe.jobs.macos
import zink_probe.jobs.macos_probe
"""
    subprocess.run([sys.executable, "-I", "-c", code], check=True, capture_output=True)
    with pytest.raises(SystemExit) as result:
        main(["--address", ADDRESS, "--device-id", DEVICE_ID, "--print"])
    assert result.value.code == 2


def test_native_delegate_metadata_without_bluetooth_connection():
    pytest.importorskip("IOBluetooth")
    from zink_probe.jobs.macos import _NativeBackend

    backend = _NativeBackend()
    stream = make_stream(backend)
    delegate = backend.delegate(stream)
    for selector in (
        "rfcommChannelOpenComplete_status_",
        "rfcommChannelData_data_length_",
        "rfcommChannelWriteComplete_refcon_status_",
        "rfcommChannelClosed_",
    ):
        assert getattr(delegate, selector).__metadata__()["retval"]["type"] == b"v"
    data_argument = delegate.rfcommChannelData_data_length_.__metadata__()["arguments"][
        3
    ]
    assert data_argument["type"] == b"n^v"
    assert data_argument["c_array_length_in_arg"] == 4
    delegate.owner = None
