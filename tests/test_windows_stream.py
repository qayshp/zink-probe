"""Windows stream tests use real local sockets and the default asyncio loop."""

import asyncio
import ctypes as C
import socket
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest
from test_linux_stream import ADDRESS, LOCAL, ROOT, QuietTrace
from test_linux_stream import Harness as SocketHarness

from zink_probe.jobs import FramedSession, JobEngine, JobJournal, JobSpec
from zink_probe.jobs.diagnostics import ReadOnlySession, inspect_printer
from zink_probe.jobs.simulator import DEVICE_ID, SimulatedPrinter
from zink_probe.jobs.windows import (
    WindowsRfcommStream,
    _cached_call,
    normalize_address,
    select_device,
)
from zink_probe.jobs.windows_native import (
    BluetoothApi,
    DeviceInfo,
    NativeSocket,
    RadioInfo,
    RadioParams,
    SockaddrBth,
    WinsockApi,
    cached_devices,
    sockaddr,
)
from zink_probe.jobs.windows_probe import main, run_checks
from zink_probe.protocol import ProtocolError, validate_request


def run(coroutine):
    # In Windows CI this is the default ProactorEventLoop, not a selector override.
    return asyncio.run(coroutine)


def records():
    return [
        dict(
            local_address=LOCAL,
            address=ADDRESS,
            known=True,
            authenticated=True,
            remembered=True,
            connected=False,
        )
    ]


class Harness(SocketHarness):
    async def inspect(self, address, adapter):
        self.inspections += 1
        if self.inspection_error:
            raise self.inspection_error
        return select_device(records(), address, adapter)

    def stream(self, **kwargs):
        return WindowsRfcommStream(
            ADDRESS,
            _socket_factory=lambda: self.facade,
            _inspect=self.inspect,
            **kwargs,
        )


def test_parameters_and_windows_abi():
    assert normalize_address("aa-bb-cc-dd-ee-ff") == "AA:BB:CC:DD:EE:FF"
    for bad in (None, "BLE-UUID", "aa:bb-cc:dd:ee:ff", "aabbccddeeff"):
        with pytest.raises(ValueError):
            WindowsRfcommStream(bad)
    for options in (
        {"adapter": "hci0"},
        {"timeout": 0},
        {"timeout": float("nan")},
        {"timeout": float("inf")},
        {"write_chunk_size": 0},
        {"write_chunk_size": True},
    ):
        with pytest.raises(ValueError):
            WindowsRfcommStream(ADDRESS, **options)
    assert C.sizeof(SockaddrBth) == 30
    assert (
        SockaddrBth.address.offset,
        SockaddrBth.service.offset,
        SockaddrBth.port.offset,
    ) == (2, 10, 26)
    value = sockaddr(ADDRESS, 2)
    assert bytes(value) == bytes.fromhex("20005544332211000000") + bytes(
        16
    ) + bytes.fromhex("02000000")
    assert C.sizeof(RadioParams) == 4
    assert C.sizeof(RadioInfo) == 520
    assert C.sizeof(DeviceInfo) == 560
    assert DeviceInfo.authenticated.offset == 28 and DeviceInfo.name.offset == 64


@pytest.mark.parametrize(
    "change,match",
    [
        ("missing", "radio"),
        ("unpaired", "not paired"),
        ("unknown", "not paired"),
        ("wrong-address", "not paired"),
        ("ambiguous", "multiple radios"),
    ],
)
def test_cached_selection_requires_exact_pairing(change, match):
    data = records()
    if change == "missing":
        data.clear()
    elif change == "unpaired":
        data[0]["authenticated"] = False
    elif change == "unknown":
        data[0]["known"] = False
    elif change == "wrong-address":
        data[0]["address"] = LOCAL
    else:
        data.append(dict(data[0], local_address="AA:BB:CC:DD:EE:FF"))
        assert select_device(data, ADDRESS, LOCAL) == data[0]
    with pytest.raises(ConnectionError, match=match):
        select_device(data, ADDRESS)


@pytest.mark.parametrize(
    "failure", [None, "first", "radio", "device", "unknown", "next"]
)
def test_cached_native_reads_and_handle_cleanup(failure):
    calls = []

    class Api:
        def first(self, params, radio):
            calls.append("first")
            assert params._obj.size == 4
            radio._obj.value = 42
            return None if failure == "first" else 71

        def radio_info(self, radio, info):
            calls.append("radio")
            assert radio.value == 42 and info._obj.size == 520
            info._obj.address = int(LOCAL.replace(":", ""), 16)
            return 5 if failure == "radio" else 0

        def device_info(self, radio, info):
            calls.append("device")
            assert info._obj.size == 560
            assert info._obj.address == int(ADDRESS.replace(":", ""), 16)
            info._obj.authenticated = info._obj.remembered = 1
            return {"device": 5, "unknown": 1168}.get(failure, 0)

        def close_radio(self, radio):
            assert radio.value == 42
            calls.append("close-radio")

        def next(self, finder, radio):
            assert finder == 71
            calls.append("next")
            return False

        def close_find(self, finder):
            assert finder == 71
            calls.append("close-find")

        def last_error(self):
            return 5 if failure in ("first", "next") else 259

    if failure in ("first", "radio", "device", "next"):
        with pytest.raises(OSError):
            cached_devices(ADDRESS, _api=Api())
    else:
        result = cached_devices(ADDRESS, _api=Api())
        assert result[0]["known"] == (failure != "unknown")
        assert result[0]["authenticated"] == (failure != "unknown")
    assert (
        calls.count("close-radio") == calls.count("close-find") == (failure != "first")
    )
    assert set(calls) <= {
        "first",
        "radio",
        "device",
        "next",
        "close-radio",
        "close-find",
    }


def test_native_socket_packs_addresses_and_returns_winsock_errors():
    calls = []
    sock, peer = socket.socketpair()

    class Api:
        def bind(self, handle, ptr, size):
            calls.append(("bind", handle, bytes(ptr._obj), size))
            return 0

        def connect(self, handle, ptr, size):
            calls.append(("connect", handle, bytes(ptr._obj), size))
            return -1

        def last_error(self):
            return 10035

    wrapper = NativeSocket(_api=Api(), _socket=sock)
    try:
        wrapper.setblocking(False)
        wrapper.bind((LOCAL, 0))
        assert wrapper.connect_ex((ADDRESS, 2)) == 10035
        assert calls == [
            ("bind", sock.fileno(), bytes(sockaddr(LOCAL, 0)), 30),
            ("connect", sock.fileno(), bytes(sockaddr(ADDRESS, 2)), 30),
        ]
        assert wrapper.send(b"test") == 4 and peer.recv(4) == b"test"
        peer.sendall(b"reply")
        assert wrapper.recv(5) == b"reply"
    finally:
        wrapper.close()
        peer.close()
    assert sock.fileno() == -1


def test_cancel_metadata_worker_cannot_continue_opening_socket():
    gate = threading.Event()
    finished = threading.Event()

    def delayed():
        gate.wait(2)
        finished.set()
        return records()

    async def case():
        h = Harness()
        stream = h.stream(timeout=0.02)

        async def inspect(*args):
            return select_device(await _cached_call(delayed), ADDRESS)

        stream._inspect = inspect
        with pytest.raises(TimeoutError):
            await stream.open()
        gate.set()
        for _ in range(100):
            if finished.is_set():
                break
            await asyncio.sleep(0.001)
        await asyncio.sleep(0.01)
        assert finished.is_set() and stream.state == "closed"
        assert h.facade.connects == h.facade.closed == 0
        await h.finish()

    try:
        run(case())
    finally:
        gate.set()


def test_exceptional_connect_readiness_is_not_success(monkeypatch):
    async def case():
        h = Harness()
        h.facade.connect_code = 10035
        h.facade.socket_error = 10013
        stream = h.stream()
        with monkeypatch.context() as patch:
            patch.setattr(
                "zink_probe.jobs.windows.select.select", lambda r, w, x, t: ([], [], x)
            )
            with pytest.raises(OSError, match="pairing"):
                await stream.open()
        assert h.facade.closed == 1 and not h.facade.sent
        await h.finish()

    run(case())


def test_lazy_imports_and_read_only_cli():
    code = """
import sys
class ForbidNative:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[-1] in {'windows_native', 'dbus_fast', 'objc', 'IOBluetooth', 'bleak', 'PIL'}:
            raise AssertionError(fullname)
sys.meta_path.insert(0, ForbidNative())
import zink_probe.jobs.windows
import zink_probe.jobs.windows_probe
"""
    subprocess.run([sys.executable, "-I", "-c", code], check=True, capture_output=True)
    with pytest.raises(SystemExit) as exc:
        main(["--address", ADDRESS, "--device-id", DEVICE_ID, "--print"])
    assert exc.value.code == 2


def test_native_windows_dll_bindings_without_radio_access():
    if sys.platform != "win32":
        pytest.skip("Windows native DLL smoke check")
    api, winsock = BluetoothApi(), WinsockApi()
    assert api.device_info.restype is C.c_uint32
    assert api.first.restype is C.c_void_p
    assert winsock.connect.argtypes == (C.c_size_t, C.c_void_p, C.c_int)
    # Read/write through the real Python-owned Windows socket wrapper, without
    # a radio enumeration, Bluetooth socket, discovery, pairing or connection.
    sock, peer = socket.socketpair()
    native = NativeSocket(_socket=sock)
    try:
        assert native.send(b"abc") == 3 and peer.recv(3) == b"abc"
    finally:
        native.close()
        peer.close()


def test_fragmented_stream_and_inprogress_connect():
    async def case():
        h = Harness()
        h.facade.connect_code = 10035
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
        assert stream.state == "closed"
        assert h.facade.closed == 1 and h.facade.connects == 1
        with pytest.raises(RuntimeError, match="single-use"):
            await stream.open()
        await h.finish()

    run(case())


@pytest.mark.parametrize("pending", [False, True])
def test_connect_error_closes_and_releases_lease(pending):
    async def case():
        h = Harness()
        h.facade.connect_code = 10035 if pending else 10013
        h.facade.socket_error = 10013
        stream = h.stream()
        with pytest.raises(OSError, match="permissions"):
            await stream.open()
        assert stream.state == "closed" and h.facade.closed == 1
        assert not h.facade.sent
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
            h.facade.connect_code = 10035
            stream._ready = hang
        else:
            await stream.open()
        with pytest.raises(TimeoutError):
            if phase == "read":
                await stream.read(10)
            else:
                await stream.open()
        assert stream.state == "closed"
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
        assert stream.state == "open"
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
        assert stream.state == "closed"
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
        assert stream.state == "open"
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
            await task
        assert stream.state == "closed"
        assert stream.tx_bytes == 0
        await h.finish()

    run(case())


def test_second_owner_cannot_release_first_lease():
    async def case():
        h, other = Harness(), Harness()
        first, second = h.stream(), other.stream()
        await first.open()
        for candidate in (second, other.stream()):
            with pytest.raises(ConnectionError, match="active Windows stream"):
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
        job = JobSpec(
            payload, name="WINDOWS-SIM", allow_alternative_sampling=alternative
        )
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
            adapter=LOCAL,
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
