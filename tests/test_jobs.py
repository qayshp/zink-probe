"""Portable job lifecycle, stream faults, and durable no-resubmit guarantees."""

import asyncio
import hashlib
import json
import struct
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from zink_probe.jobs import FramedSession, JobEngine, JobJournal, JobSpec
from zink_probe.jobs.journal import SubmissionBlocked
from zink_probe.jobs.model import UploadPlan, jpeg_info
from zink_probe.jobs.simulator import DEVICE_ID, ScriptedStream, SimulatedPrinter
from zink_probe.jobs.transport import frame
from zink_probe.protocol import ProtocolError, RfcommParser, validate_request

ROOT = Path(__file__).resolve().parents[1]
JPEG = (ROOT / "experiments/calibration/package-v2/python.jpg").read_bytes()
HIGH = (ROOT / "experiments/jpeg-quality/q100-444-optimized.jpg").read_bytes()


@pytest.fixture
def journal(tmp_path):
    with JobJournal(tmp_path / "jobs.sqlite") as value:
        yield value


def spec(**kwargs):
    return JobSpec(JPEG, name="SELECT-CAL-02", **kwargs)


def engine(printer, journal, **kwargs):
    return JobEngine(
        FramedSession(printer, timeout=0.03),
        journal,
        DEVICE_ID,
        poll_interval=0,
        observation_timeout=0.15,
        **kwargs,
    )


def test_encoding_description_and_explicit_alternative():
    ordinary = spec(encoder_quality=90)
    assert ordinary.encoding["sampling"] == "4:2:0"
    assert ordinary.encoding["declared_encoder_quality"] == 90
    assert (
        ordinary.sha256
        == "14e1530787508578341510cbdf827352a604d19b1b14039fc3cf785e26078206"
    )
    with pytest.raises(ProtocolError, match="opt-in"):
        JobSpec(HIGH)
    high = JobSpec(HIGH, allow_alternative_sampling=True, encoder_quality=100)
    assert high.encoding["sampling"] == "4:4:4"
    assert high.encoding["quantization_all_ones"]


@pytest.mark.parametrize(
    "data",
    [b"", b"png", JPEG[:-2], b"\xff\xd8\xff\xe0\xff\xff\xff\xd9"],
    # Pytest puts node IDs in PYTEST_CURRENT_TEST; a whole JPEG exceeds the
    # Windows environment-variable limit before the test can even run.
    ids=["empty", "wrong-format", "missing-eoi", "truncated-segment"],
)
def test_invalid_image_envelope(data):
    with pytest.raises(ProtocolError):
        jpeg_info(data)


def test_progressive_and_wrong_geometry_refused():
    location = JPEG.index(b"\xff\xc0")
    for offset, byte in [(location + 1, 0xC2), (location + 4, 12), (location + 8, 1)]:
        data = bytearray(JPEG)
        data[offset] = byte
        with pytest.raises(ProtocolError):
            jpeg_info(bytes(data))


@pytest.mark.parametrize(
    "values",
    [{"copies": 0}, {"copies": True}, {"copies": 256}, {"encoder_quality": 101}],
)
def test_bad_job_parameters(values):
    with pytest.raises(ProtocolError):
        spec(**values)


def test_plan_golden_vectors_and_frame_limits():
    plan = UploadPlan(spec(), 1000, 16)
    # Independently retained CAL-02 payload length and original-app property layout.
    assert plan.next_message().hex() == "0c01d4c90100"
    plan.accept(bytes.fromhex("0d030c00"))
    assert plan.next_message().hex() == "300c000301010d53454c4543542d43414c2d3032"
    plan.accept(b"\x31")
    chunk = plan.next_message()
    assert len(chunk) == 1000 and chunk[:2] == b"\x0e\x03"
    assert RfcommParser().feed(frame(chunk)) == [chunk]
    assert frame(bytes(255))[:5] == b"HP+\x01\xff"
    assert frame(bytes(256))[:6] == b"HP+\x02\x00\x01"
    with pytest.raises(ProtocolError):
        frame(bytes(4097))


@pytest.mark.parametrize("copies", [1, 3])
@pytest.mark.parametrize("read_size", [1, 17, 4096])
def test_complete_job_exact_bytes_copies_and_durable_intent(journal, copies, read_size):
    job = spec(copies=copies)

    def audit(request, response, printer):
        if request[0] in (12, 14, 48):
            saved = journal.get(job.local_id)
            assert saved["state"] == "request_pending"
            assert saved["pending"]["sha256"] == hashlib.sha256(request).hexdigest()
        return response

    printer = SimulatedPrinter(
        read_size=read_size, write_fragment=3, fault=audit, copies_expected=copies
    )
    result = asyncio.run(engine(printer, journal).run(job))
    assert result.state == "completed", result
    assert result.acknowledged_bytes == len(JPEG)
    assert not result.physical_ejection_confirmed
    assert bytes(printer.uploaded) == JPEG
    assert printer.name == job.name and printer.copies == copies
    assert [m[0] for m in printer.mutations].count(12) == 1
    assert [m[0] for m in printer.mutations].count(48) == 1
    assert [m[0] for m in printer.mutations].count(14) == 118
    assert printer.pages == 11 + copies and printer.closed
    states = [r["state"] for r in journal.history(job.local_id)]
    assert all(
        state in states
        for state in (
            "claimed",
            "accepted",
            "uploading",
            "uploaded",
            "printing",
            "completed",
        )
    )
    assert (
        journal.get(job.local_id)["last_observation"]["status"][
            "print_progress_percent"
        ]
        == 0
    )


def test_quality100_exact_payload_simulation(journal):
    printer = SimulatedPrinter()
    job = JobSpec(
        HIGH, name="SELECT-CAL-03", allow_alternative_sampling=True, encoder_quality=100
    )
    result = asyncio.run(engine(printer, journal).run(job))
    assert result.state == "completed"
    assert bytes(printer.uploaded) == HIGH
    assert sum(m[0] == 14 for m in printer.mutations) == 152


def test_plan_against_every_ack_from_physical_cal03_trace():
    evidence = json.loads(
        (ROOT / "experiments/calibration/package-v3/print-evidence.json").read_text()
    )
    vectors = evidence["wire_vectors"]
    job = JobSpec(
        HIGH, name="SELECT-CAL-03", allow_alternative_sampling=True, encoder_quality=100
    )
    plan = UploadPlan(job, 1000, evidence["job_name_max"])
    assert plan.next_message().hex() == vectors["start_request"]
    plan.accept(bytes.fromhex(vectors["start_reply"]))
    assert plan.next_message().hex() == vectors["properties_request"]
    plan.accept(bytes.fromhex(vectors["properties_reply"]))
    uploaded = bytearray()
    for reply in vectors["file_write_replies"]:
        uploaded.extend(plan.next_message()[2:])
        plan.accept(bytes.fromhex(reply))
    assert plan.phase == "uploaded" and bytes(uploaded) == HIGH
    assert hashlib.sha256(uploaded).hexdigest() == evidence["payload_sha256"]


@pytest.mark.parametrize(
    "change",
    [
        "model",
        "identity",
        "name",
        "unicode",
        "pause",
        "battery",
        "queue",
        "flags",
        "capability",
        "maximum",
    ],
)
def test_preflight_failure_never_allocates(journal, change):
    printer, job = SimulatedPrinter(), spec()
    if change == "model":
        printer.model = 0x48D4
    if change == "identity":
        printer.device_id = "ff" * 16
    if change == "name":
        job = replace(job, name="SELECT-CAL-03 Q100 444")
    if change == "unicode":
        job = replace(job, name="é" * 9)
    if change == "pause":
        printer.paused = True
    if change == "battery":
        printer.battery = 20
    if change == "queue":
        printer.extra_jobs = [9]
    if change == "flags":
        printer.status_overrides["system_flags"] = 8
    if change == "capability":
        printer.features["requests"].remove(12)
    if change == "maximum":
        printer.maximum = 8
    result = asyncio.run(engine(printer, journal).run(job))
    assert result.state == "not_submitted"
    assert not printer.mutations and printer.closed
    assert journal.get(job.local_id) is None


def test_utf8_exact_limit(journal):
    printer = SimulatedPrinter()
    result = asyncio.run(engine(printer, journal).run(replace(spec(), name="é" * 8)))
    assert result.state == "completed" and printer.name == "é" * 8


@pytest.mark.parametrize("opcode", [12, 48, 14])
def test_lost_ack_never_resends_and_survives_restart(tmp_path, opcode):
    path, job = tmp_path / "jobs.sqlite", spec()
    printer = SimulatedPrinter(
        fault=lambda req, reply, p: None if req[0] == opcode else reply
    )
    with JobJournal(path) as journal:
        result = asyncio.run(engine(printer, journal).run(job))
        assert result.state == "uncertain"
        assert sum(m[0] == opcode for m in printer.mutations) == 1
        assert journal.get(job.local_id)["pending"]["opcode"] == opcode
    with JobJournal(path) as journal:
        other = SimulatedPrinter()
        with pytest.raises(SubmissionBlocked):
            asyncio.run(engine(other, journal).run(job))
        assert other.requests == [] and other.closed
        another = SimulatedPrinter()
        with pytest.raises(SubmissionBlocked):
            asyncio.run(engine(another, journal).run(spec()))
        assert not another.mutations


def test_explicit_start_rejection_is_distinct_from_unknown(journal):
    printer = SimulatedPrinter(
        fault=lambda req, reply, p: b"\x01\x0c\x08" if req[0] == 12 else reply
    )
    result = asyncio.run(engine(printer, journal).run(spec()))
    assert result.state == "rejected"
    assert len(printer.mutations) == 1


@pytest.mark.parametrize(
    "reply",
    [
        b"\x01\x30\x07",
        b"\x01\x30\x12",
        b"\x01\x0e\x08",
        b"\x31\x00",
    ],
)
def test_property_failure_never_uploads_or_retries(journal, reply):
    printer = SimulatedPrinter(
        fault=lambda req, response, p: reply if req[0] == 48 else response
    )
    result = asyncio.run(engine(printer, journal).run(spec()))
    assert result.state in ("stopped", "uncertain")
    assert [m[0] for m in printer.mutations] == [12, 48]


@pytest.mark.parametrize(
    "handle,status,received,total",
    [
        (8, 1, 998, len(JPEG)),
        (7, 1, 997, len(JPEG)),
        (7, 1, 999, len(JPEG)),
        (7, 2, 998, len(JPEG)),
        (7, 1, 998, 1),
        (7, 3, 998, len(JPEG)),
        (7, 4, 998, len(JPEG)),
    ],
)
def test_invalid_upload_ack_stops(journal, handle, status, received, total):
    bad = b"\x0f" + struct.pack("<BBII", handle, status, received, total)
    printer = SimulatedPrinter(
        fault=lambda req, response, p: bad if req[0] == 14 else response
    )
    result = asyncio.run(engine(printer, journal).run(spec()))
    assert result.state == "uncertain"
    assert len(printer.uploaded) == 998
    assert sum(m[0] == 14 for m in printer.mutations) == 1


def test_optional_single_empty_final_message(journal):
    printer = SimulatedPrinter()
    printer.require_empty_final = True
    result = asyncio.run(engine(printer, journal).run(spec()))
    assert result.state == "completed"
    assert printer.mutations[-1] == b"\x0e\x07"
    assert len(printer.uploaded) == len(JPEG)


def test_repeated_empty_final_refused(journal):
    def fault(req, reply, p):
        if req == b"\x0e\x07":
            return reply[:2] + b"\x01" + reply[3:]
        return reply

    printer = SimulatedPrinter(fault=fault)
    printer.require_empty_final = True
    result = asyncio.run(engine(printer, journal).run(spec()))
    assert result.state == "uncertain"
    assert sum(m == b"\x0e\x07" for m in printer.mutations) == 1


def test_write_failure_after_remote_acceptance_is_uncertain(journal):
    printer = SimulatedPrinter(
        fault=lambda req, reply, p: (
            ConnectionError("sent then disconnected") if req[0] == 12 else reply
        )
    )
    result = asyncio.run(engine(printer, journal).run(spec()))
    assert result.state == "uncertain" and result.job_id is None
    assert printer.expected_bytes == len(JPEG)
    assert len(printer.mutations) == 1


def test_disappearance_without_printing_is_not_completion(journal):
    printer = SimulatedPrinter()
    printer.disappear_without_print = True
    result = asyncio.run(engine(printer, journal).run(spec()))
    assert result.state == "uncertain"
    assert printer.pages == 11


@pytest.mark.parametrize(
    "change", ["extra_pages", "counter_reset", "calibration", "foreign", "jam", "pause"]
)
def test_ambiguous_or_blocked_completion_stays_uncertain(journal, change):
    def fault(req, reply, p):
        if p.finished_upload and req[0] == 58:
            if change == "extra_pages":
                p.pages = 14
            if change == "counter_reset":
                p.pages = 0
            if change == "calibration":
                p.calibrations = 3
            if change == "foreign":
                p.extra_jobs = [77]
            if change == "jam":
                p.status_overrides["print_status_code"] = 4
            if change == "pause":
                p.status_overrides["queue_status_code"] = 3
        return reply

    printer = SimulatedPrinter(fault=fault)
    result = asyncio.run(engine(printer, journal).run(spec()))
    assert result.state == "uncertain"


def test_reconcile_known_printing_job_uses_reads_only(journal):
    def fault(req, reply, p):
        return None if req[0] == 8 and p.finished_upload and p.polls == 2 else reply

    printer, job = SimulatedPrinter(fault=fault), spec()
    result = asyncio.run(engine(printer, journal).run(job))
    assert result.state == "uncertain"
    assert journal.get(job.local_id)["seen_printing"]
    before = len(printer.requests)
    printer.closed = printer.hang = False
    printer.fault = None
    result = asyncio.run(engine(printer, journal).reconcile(job.local_id))
    assert result.state == "completed"
    assert all(r[0] not in (12, 14, 48) for r in printer.requests[before:])


def test_missing_remote_id_cannot_be_guessed_on_reconciliation(journal):
    printer, job = (
        SimulatedPrinter(fault=lambda req, reply, p: None if req[0] == 12 else reply),
        spec(),
    )
    asyncio.run(engine(printer, journal).run(job))
    other = SimulatedPrinter()
    result = asyncio.run(engine(other, journal).reconcile(job.local_id))
    assert result.state == "uncertain" and result.job_id is None
    assert not other.mutations


def test_cancellation_leaves_claim_and_closes_stream(journal):
    async def exercise():
        printer, job = (
            SimulatedPrinter(
                fault=lambda req, reply, p: None if req[0] == 14 else reply
            ),
            spec(),
        )
        runner = engine(printer, journal)
        runner.session.timeout = 10
        task = asyncio.create_task(runner.run(job))
        for _ in range(1000):
            if printer.hang:
                break
            await asyncio.sleep(0)
        assert printer.hang
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert printer.closed
        assert journal.get(job.local_id)["state"] == "uncertain"
        assert journal.get(job.local_id)["pending"]["opcode"] == 14

    asyncio.run(exercise())


def test_journal_failure_before_write_prevents_mutation(journal, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(journal, "update", fail)
    printer, job = SimulatedPrinter(), spec()
    result = asyncio.run(engine(printer, journal).run(job))
    assert result.state == "uncertain" and not printer.mutations
    assert journal.get(job.local_id)["state"] == "claimed"


def test_database_enforces_one_active_claim_across_connections(tmp_path):
    path = tmp_path / "jobs.sqlite"
    with JobJournal(path) as first, JobJournal(path) as second:
        first.claim(spec(), DEVICE_ID, {})
        with pytest.raises(SubmissionBlocked):
            second.claim(spec(), DEVICE_ID, {})


@pytest.mark.parametrize(
    "chunks",
    [
        [b"BAD!"],
        [b"HP+\x02\xff\xff"],
        [b"HP+\x01\x04\x0d"],
        [frame(b"\x31")],
        [frame(b"\x0d\x07\x01\x00") * 2],
    ],
)
def test_bad_stream_poisoned_without_retransmit(chunks):
    async def exercise():
        stream = ScriptedStream(chunks)
        session = FramedSession(stream, timeout=0.02)
        with pytest.raises((ProtocolError, ConnectionError)):
            await session.exchange(b"\x0c\x01\x01\x00\x00\x00")
        with pytest.raises(ConnectionError):
            await session.exchange(b"\x0c\x01\x01\x00\x00\x00")
        assert len(stream.writes) == 1

    asyncio.run(exercise())


def test_events_fragmented_and_coalesced_are_not_replies():
    async def exercise():
        wire = (
            frame(b"\x03\x06\x00\x34\x12")
            + frame(b"\x0d\x07\x34\x12")
            + frame(b"\x03\x01\x00\x07")
        )
        for split in range(1, len(wire)):
            session = FramedSession(ScriptedStream([wire[:split], wire[split:]]))
            assert (
                await session.exchange(b"\x0c\x01\x01\x00\x00\x00")
                == b"\x0d\x07\x34\x12"
            )
            assert session.events[0] == b"\x03\x06\x00\x34\x12"

    asyncio.run(exercise())


def test_diagnostics_still_reject_job_mutations():
    for payload in (
        b"\x0c\x01\x01\x00\x00\x00",
        b"\x30\x01\x00\x03\x01",
        b"\x0e\x07x",
        b"\x38\x01\x00",
    ):
        with pytest.raises(ProtocolError):
            validate_request(payload)


def test_core_imports_without_native_modules():
    code = """
import sys
class ForbidNative:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'objc','Foundation','IOBluetooth','bleak'}:
            raise AssertionError(fullname)
sys.meta_path.insert(0,ForbidNative())
import zink_probe.jobs
import zink_probe.jobs.simulator
"""
    subprocess.run(
        [sys.executable, "-I", "-c", code], check=True, capture_output=True, text=True
    )


def test_journal_never_stores_image_bytes(journal):
    job, printer = spec(), SimulatedPrinter()
    asyncio.run(engine(printer, journal).run(job))
    encoded = json.dumps(journal.history(job.local_id))
    assert JPEG[:100].hex() not in encoded
    assert job.sha256 in encoded


def test_unknown_reconciliation_closes_stream_without_requests(journal):
    printer = SimulatedPrinter()
    with pytest.raises(ProtocolError, match="No matching"):
        asyncio.run(engine(printer, journal).reconcile("missing"))
    assert printer.closed and not printer.requests


def test_event_flood_is_bounded():
    async def exercise():
        stream = ScriptedStream([frame(b"\x03\x01") * 129])
        session = FramedSession(stream)
        with pytest.raises(ProtocolError, match="flood"):
            await session.exchange(b"\x2c")
        assert len(session.events) == 64 and session.failed

    asyncio.run(exercise())


def test_lost_final_ack_never_becomes_completed_by_guess(journal):
    def fault(request, reply, printer):
        return None if request[0] == 14 and printer.finished_upload else reply

    printer, job = SimulatedPrinter(fault=fault), spec()
    result = asyncio.run(engine(printer, journal).run(job))
    assert result.state == "uncertain"
    assert bytes(printer.uploaded) == JPEG
    assert not journal.get(job.local_id)["upload_acknowledged"]
    printer.closed = printer.hang = False
    printer.fault = None
    before = len(printer.mutations)
    result = asyncio.run(engine(printer, journal).reconcile(job.local_id))
    assert result.state == "uncertain"
    assert printer.pages == 12 and len(printer.mutations) == before


@pytest.mark.parametrize("contradiction", ["foreign", "counter"])
def test_contradictory_observation_survives_reconciliation(tmp_path, contradiction):
    path, job = tmp_path / "jobs.sqlite", spec()

    def fault(request, reply, printer):
        if printer.finished_upload and request[0] == 58:
            if contradiction == "foreign":
                printer.extra_jobs = [77]
            else:
                printer.pages = 14
        return reply

    printer = SimulatedPrinter(fault=fault)
    with JobJournal(path) as journal:
        result = asyncio.run(engine(printer, journal).run(job))
        assert result.state == "uncertain"
        record = journal.get(job.local_id)
        assert record["seen_printing"] and record["attribution_blocked"]
        assert record["last_observation"]
    printer.closed = False
    printer.fault = None
    printer.extra_jobs = []
    printer.pages = 12
    printer.polls = 10
    printer.printed = True
    mutations = len(printer.mutations)
    with JobJournal(path) as restarted:
        result = asyncio.run(engine(printer, restarted).reconcile(job.local_id))
        assert result.state == "uncertain"
        assert "Earlier contradictory" in result.error
        assert restarted.get(job.local_id)["attribution_blocked"]
    assert len(printer.mutations) == mutations
