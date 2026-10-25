"""Portable CLI workflows, immutable payloads, and no-resubmit failure paths."""

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from zink_probe import unified_cli as cli
from zink_probe.jobs import JobJournal, backends
from zink_probe.jobs.backends import SimulatedStream
from zink_probe.jobs.saved_plan import canonical, create_plan, digest, load_plan
from zink_probe.jobs.simulator import DEVICE_ID
from zink_probe.protocol import ProtocolError, validate_request

ROOT = Path(__file__).resolve().parents[1]
pytest.importorskip("PIL")


@pytest.fixture(scope="module", params=[(90, "4:2:0"), (100, "4:4:4")])
def bundle(request, tmp_path_factory):
    from zink_probe.images import PreparationOptions, prepare_comparison
    from zink_probe.prepare_cli import write_bundle

    root = tmp_path_factory.mktemp("bundles")
    options = PreparationOptions("fit", *request.param)
    write_bundle(
        root / "prepared",
        prepare_comparison(ROOT / "examples/image-preparation/source.png", options),
        options,
    )
    return root / "prepared"


def saved(bundle, tmp_path, *, simulated=True):
    path = tmp_path / "job"
    create_plan(
        bundle,
        path,
        expected_device_id=DEVICE_ID if simulated else "ab" * 16,
        simulated=simulated,
        allow_alternative_sampling=True,
    )
    return path


def invoke(capsys, *args):
    code = cli.main([str(arg) for arg in args])
    return code, json.loads(capsys.readouterr().out)


def forbidden(*args, **kwargs):
    raise AssertionError("No transport should be constructed")


def test_prepare_plan_submit_show_reconcile_workflow(tmp_path, capsys):
    bundle, plan, journal = (
        tmp_path / "prepared",
        tmp_path / "job",
        tmp_path / "jobs.sqlite",
    )
    code, prepared = invoke(
        capsys,
        "prepare",
        ROOT / "examples/image-preparation/source.png",
        bundle,
        "--mode",
        "fit",
        "--quality",
        100,
        "--subsampling",
        "4:4:4",
    )
    assert code == 0 and prepared["offline"]
    code, planned = invoke(
        capsys, "plan", bundle, plan, "--simulated", "--allow-alternative-sampling"
    )
    assert code == 0 and planned["offline"]
    identity = planned["job"]["local_id"]
    code, result = invoke(
        capsys, "submit", plan, "--journal", journal, "--log", tmp_path / "submit.jsonl"
    )
    assert code == 0 and result["simulated"] and result["offline"]
    assert result["result"]["state"] == "completed"
    assert result["result"]["local_id"] == identity
    assert result["result"]["payload_bytes_match"]
    assert result["result"]["print_start_count"] == 1
    assert not result["result"]["physical_ejection_confirmed"]
    code, shown = invoke(capsys, "show", plan, "--journal", journal)
    assert code == 0 and shown["offline"] and shown["record"]["state"] == "completed"
    code, duplicate = invoke(capsys, "submit", plan, "--journal", journal)
    assert code == 1 and "SubmissionBlocked" in duplicate["error"]
    code, reconciled = invoke(capsys, "reconcile", plan, "--journal", journal)
    assert code == 0 and reconciled["read_only"] and "log" not in reconciled


def test_plan_snapshot_survives_removed_source_and_stable_identity(bundle, tmp_path):
    source = tmp_path / "source"
    shutil.copytree(bundle, source)
    path = saved(source, tmp_path)
    shutil.rmtree(source)
    first, jpeg = load_plan(path)
    second, same = load_plan(path)
    assert first == second and jpeg == same
    assert jpeg.jpeg == (bundle / "image.jpg").read_bytes()
    with pytest.raises(FileExistsError):
        create_plan(
            bundle,
            path,
            expected_device_id=DEVICE_ID,
            simulated=True,
            allow_alternative_sampling=True,
        )
    assert load_plan(path)[0] == first


@pytest.mark.parametrize(
    "corruption", ["jpeg", "intent", "encoding", "schema", "decoder"]
)
def test_corrupt_plan_never_reaches_transport(
    bundle, tmp_path, capsys, monkeypatch, corruption
):
    path = saved(bundle, tmp_path)
    if corruption == "jpeg":
        (path / "image.jpg").write_bytes(b"invalid")
    else:
        envelope = json.loads((path / "job.json").read_text())
        if corruption == "intent":
            envelope["intent"]["copies"] = 2
        elif corruption == "encoding":
            envelope["intent"]["encoding"]["width"] = 5
        elif corruption == "schema":
            envelope["intent"]["schema_version"] = 2
        elif corruption == "decoder":
            data = bytearray((path / "image.jpg").read_bytes())
            # Valid baseline geometry/header, invalid Huffman code counts.
            # Full decoding catches this even with recomputed checksums.
            table = data.index(b"\xff\xc4")
            data[table + 5 : table + 21] = bytes([255]) * 16
            data = bytes(data)
            (path / "image.jpg").write_bytes(data)
            envelope["intent"].update(
                payload_sha256=digest(data), payload_bytes=len(data)
            )
        if corruption != "intent":
            envelope["intent_sha256"] = digest(canonical(envelope["intent"]))
        (path / "job.json").write_bytes(canonical(envelope))
    monkeypatch.setattr(cli, "stream_factory", forbidden)
    code, result = invoke(capsys, "submit", path, "--journal", tmp_path / "jobs.sqlite")
    assert code == 1 and not result["ok"]
    assert not (tmp_path / "jobs.sqlite").exists()


def test_bundle_hash_and_alternative_sampling_checked(bundle, tmp_path):
    copied = tmp_path / "bundle"
    shutil.copytree(bundle, copied)
    manifest = json.loads((copied / "manifest.json").read_text())
    if manifest["variants"]["fit"]["encoding"]["subsampling"] != "4:2:0":
        with pytest.raises(ProtocolError, match="opt-in"):
            create_plan(
                copied, tmp_path / "no", expected_device_id=DEVICE_ID, simulated=True
            )
    (copied / "image.jpg").write_bytes(
        (copied / "image.jpg").read_bytes().replace(b"JFIF", b"ABCD", 1)
    )
    with pytest.raises(ProtocolError, match="mismatch"):
        create_plan(
            copied,
            tmp_path / "no",
            expected_device_id=DEVICE_ID,
            simulated=True,
            allow_alternative_sampling=True,
        )
    assert not (tmp_path / "no").exists()


def test_simulated_status_allowlist_and_private_output(tmp_path, capsys, monkeypatch):
    printer = SimulatedStream()
    monkeypatch.setattr(cli, "stream_factory", lambda *a: lambda *a, **k: printer)
    code, result = invoke(
        capsys, "status", "--transport", "simulated", "--log", tmp_path / "status.jsonl"
    )
    assert code == 0 and result["read_only"] and result["simulated"]
    assert not printer.mutations and printer.closed
    for request in printer.requests:
        validate_request(request, {9})
    assert result["sessions"][0]["status"]["battery_percent"] == 100
    assert result["sessions"][0]["counters_unchanged"]
    assert DEVICE_ID not in json.dumps(result)


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--address", "00:11:22:33:44:55"],
        ["--device-id", DEVICE_ID],
        ["--transport", "simulated", "--address", "00:11:22:33:44:55"],
    ],
)
def test_status_requires_explicit_target_before_factory(capsys, monkeypatch, args):
    monkeypatch.setattr(cli, "stream_factory", forbidden)
    code, result = invoke(capsys, "status", *args)
    assert code == 1 and "error" in result and "log" not in result


def test_lost_start_reply_blocks_second_submission(
    bundle, tmp_path, capsys, monkeypatch
):
    plan = saved(bundle, tmp_path)
    printer = SimulatedStream()
    printer.fault = lambda request, response, _: (
        ConnectionError("lost after allocation") if request[0] == 12 else response
    )
    monkeypatch.setattr(cli, "stream_factory", lambda *a: lambda *a, **k: printer)
    journal = tmp_path / "jobs.sqlite"
    code, result = invoke(
        capsys, "submit", plan, "--journal", journal, "--log", tmp_path / "fault.jsonl"
    )
    assert code == 3 and result["record"]["state"] == "uncertain"
    assert result["record"]["pending"]["opcode"] == 12
    assert printer.closed and len(printer.mutations) == 1
    monkeypatch.setattr(cli, "stream_factory", forbidden)
    code, repeat = invoke(capsys, "submit", plan, "--journal", journal)
    assert code == 3 and "SubmissionBlocked" in repeat["error"]
    # A new plan ID is not a workaround for the unresolved printer claim.
    second = tmp_path / "another-job"
    create_plan(
        bundle,
        second,
        expected_device_id=DEVICE_ID,
        simulated=True,
        allow_alternative_sampling=True,
    )
    code, blocked = invoke(capsys, "submit", second, "--journal", journal)
    assert code == 1 and "SubmissionBlocked" in blocked["error"]


def test_reconciliation_after_lost_status_only_reads(
    bundle, tmp_path, capsys, monkeypatch
):
    plan = saved(bundle, tmp_path)
    printer = SimulatedStream()
    printer.fault = lambda request, response, p: (
        ConnectionError("lost status")
        if request[0] == 8 and p.finished_upload
        else response
    )
    monkeypatch.setattr(cli, "stream_factory", lambda *a: lambda *a, **k: printer)
    journal = tmp_path / "jobs.sqlite"
    code, result = invoke(
        capsys, "submit", plan, "--journal", journal, "--log", tmp_path / "fault.jsonl"
    )
    assert code == 3 and result["record"]["upload_acknowledged"]
    start = len(printer.requests)
    mutations = list(printer.mutations)
    printer.closed, printer.fault = (
        False,
        None,
    )  # New connection to same simulated state.
    code, result = invoke(
        capsys,
        "reconcile",
        plan,
        "--journal",
        journal,
        "--log",
        tmp_path / "reconcile.jsonl",
    )
    assert code == 0 and result["read_only"]
    assert printer.mutations == mutations and printer.closed
    for request in printer.requests[start:]:
        validate_request(request, set())


@pytest.mark.parametrize(
    "failure", ["wrong-identity", "battery", "paused", "open", "deadline"]
)
def test_preflight_and_deadline_failures(
    bundle, tmp_path, capsys, monkeypatch, failure
):
    plan = saved(bundle, tmp_path)
    printer = SimulatedStream()
    if failure == "wrong-identity":
        printer.device_id = "ab" * 16
    elif failure == "battery":
        printer.battery = 5
    elif failure == "paused":
        printer.paused = True
    elif failure == "open":

        async def fail():
            raise ConnectionError("open failed")

        printer.open = fail
    else:
        printer.fault = lambda request, response, _: (
            None if request[0] == 12 else response
        )
    monkeypatch.setattr(cli, "stream_factory", lambda *a: lambda *a, **k: printer)
    code, result = invoke(
        capsys,
        "submit",
        plan,
        "--journal",
        tmp_path / "jobs.sqlite",
        "--log",
        tmp_path / "trace.jsonl",
        "--operation-timeout",
        1 if failure == "deadline" else 10,
    )
    assert printer.closed
    if failure == "deadline":
        assert code == 3 and result["record"]["state"] == "uncertain"
        assert result["record"]["pending"]["opcode"] == 12
    else:
        assert code == 1 and not printer.mutations


def test_cancellation_retains_claim_and_closes(bundle, tmp_path):
    plan = saved(bundle, tmp_path)
    intent, spec = load_plan(plan)
    printer = SimulatedStream()
    printer.fault = lambda request, response, _: None if request[0] == 12 else response
    args = cli.parser().parse_args(
        ["submit", str(plan), "--journal", str(tmp_path / "jobs.sqlite")]
    )
    with JobJournal(args.journal) as journal:

        async def run():
            task = asyncio.create_task(
                cli._job(args, intent, spec, journal, None, lambda *a, **k: printer)
            )
            while not printer.mutations:
                await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(run())
        assert printer.closed and journal.get(spec.local_id)["state"] == "uncertain"


def test_reconcile_and_show_do_not_create_missing_journal(
    bundle, tmp_path, capsys, monkeypatch
):
    plan = saved(bundle, tmp_path)
    monkeypatch.setattr(cli, "stream_factory", forbidden)
    for command in ("show", "reconcile"):
        code, _ = invoke(
            capsys, command, plan, "--journal", tmp_path / "missing.sqlite"
        )
        assert code == 1 and not (tmp_path / "missing.sqlite").exists()


def test_changed_intent_cannot_reuse_journal_record(
    bundle, tmp_path, capsys, monkeypatch
):
    plan = saved(bundle, tmp_path)
    intent, spec = load_plan(plan)
    journal = tmp_path / "jobs.sqlite"
    with JobJournal(journal) as records:
        records.claim(spec, DEVICE_ID, {})
    envelope = json.loads((plan / "job.json").read_text())
    envelope["intent"]["copies"] = 2
    envelope["intent_sha256"] = digest(canonical(envelope["intent"]))
    (plan / "job.json").write_bytes(canonical(envelope))
    monkeypatch.setattr(cli, "stream_factory", forbidden)
    code, result = invoke(capsys, "reconcile", plan, "--journal", journal)
    assert code == 1 and "original job" in result["error"]


@pytest.mark.parametrize(
    "simulated,transport",
    [(True, "macos"), (True, "linux"), (True, "windows"), (False, "simulated")],
)
def test_mode_cannot_be_changed_at_submission(
    bundle, tmp_path, capsys, monkeypatch, simulated, transport
):
    plan = saved(bundle, tmp_path, simulated=simulated)
    monkeypatch.setattr(cli, "stream_factory", forbidden)
    code, result = invoke(
        capsys,
        "submit",
        plan,
        "--journal",
        tmp_path / "jobs.sqlite",
        "--transport",
        transport,
    )
    assert code == 1 and "log" not in result


@pytest.mark.parametrize(
    "platform,expected", [("darwin", "macos"), ("linux", "linux"), ("win32", "windows")]
)
def test_native_dispatch_and_adapter_factory_without_hardware(
    monkeypatch, platform, expected
):
    monkeypatch.setattr(backends.sys, "platform", platform)
    assert backends.resolve_transport("auto") == expected
    assert backends.resolve_transport(expected) == expected
    factory = backends.stream_factory(expected)
    stream = factory("00:11:22:33:44:55")
    assert stream.state == "new"
    assert (
        stream.__class__.__name__
        == {
            "macos": "MacOSRfcommStream",
            "linux": "LinuxRfcommStream",
            "windows": "WindowsRfcommStream",
        }[expected]
    )
    with pytest.raises(ValueError):
        backends.resolve_transport("windows" if expected != "windows" else "macos")


def test_cli_help_imports_without_optional_or_native_modules():
    script = """
import sys
class Block:
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in ('PIL', 'bleak', 'objc', 'IOBluetooth', 'Foundation', 'dbus_fast'):
            raise AssertionError(fullname)
sys.meta_path.insert(0, Block())
from zink_probe.unified_cli import parser
parser().format_help()
assert not any(name.startswith('zink_probe.jobs.windows_native') for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_failed_status_is_in_trace_and_closes(tmp_path, capsys, monkeypatch):
    printer = SimulatedStream()

    async def fail():
        raise TimeoutError()

    printer.open = fail
    monkeypatch.setattr(cli, "stream_factory", lambda *a: lambda *a, **k: printer)
    path = tmp_path / "failed.jsonl"
    code, result = invoke(capsys, "status", "--transport", "simulated", "--log", path)
    assert code == 1 and printer.closed and not printer.requests
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert events[-1]["event"] == "adapter_check_failed"
    assert events[-1]["error"] == result["error"] == "TimeoutError: Operation timed out"
