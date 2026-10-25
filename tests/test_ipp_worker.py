"""Real raster decoding/preparation; deterministic transport and failure guards."""

import json
import struct
import time
from uuid import uuid4

import pytest

pytest.importorskip("PIL")
from PIL import Image

from zink_probe import ipp_worker as worker
from zink_probe.jobs.backends import SimulatedStream


def setup(tmp_path, mode="capture", size=(64, 96), **extra):
    (tmp_path / "incoming").mkdir(exist_ok=True)
    key = str(uuid4())
    path = tmp_path / "incoming" / f"{key}.rgb"
    image = Image.new("RGB", size, (40, 90, 180))
    path.write_bytes(b"ZRGB" + struct.pack(">II", *size) + image.tobytes())
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"schema": 1, "mode": mode, "data_dir": str(tmp_path), **extra})
    )
    return config, path, key


def forbidden(*args, **kwargs):
    raise AssertionError("Capture/validation must never construct Bluetooth")


@pytest.mark.parametrize(
    "quality,sampling,q", [(3, "4:2:0", 85), (4, "4:2:0", 90), (5, "4:4:4", 100)]
)
def test_capture_prepares_without_transport(
    tmp_path, monkeypatch, quality, sampling, q
):
    monkeypatch.setattr(worker, "stream_factory", forbidden)
    args = setup(tmp_path)
    code, record = worker.process(*args, quality)
    assert code == 0 and record["state"] == "captured"
    assert record["encoding"]["sampling"] == sampling
    assert not record["bluetooth_opened"] and not record["physical_ejection_confirmed"]
    output = tmp_path / "jobs" / args[2]
    assert json.loads((output / "result.json").read_text()) == record
    with Image.open(output / "image.jpg") as image:
        image.load()
        assert image.size == (768, 1152)
    assert not args[1].exists()


@pytest.mark.parametrize("quality", [4, 5])
def test_simulated_job_uses_exact_prepared_payload(tmp_path, quality):
    args = setup(tmp_path, "simulated")
    code, record = worker.process(*args, quality)
    assert code == 0 and record["state"] == "completed"
    assert record["payload_bytes_match"] and record["print_start_count"] == 1
    assert not record["physical_ejection_confirmed"]


def test_replayed_capture_cannot_become_live(tmp_path, monkeypatch):
    args = setup(tmp_path)
    raw = args[1].read_bytes()
    assert worker.process(*args, 4)[0] == 0
    args[1].write_bytes(raw)
    config = json.loads(args[0].read_text())
    config.update(
        mode="live", address="00:11:22:33:44:55", device_id="ab" * 16, live_after_ns=1
    )
    args[0].write_text(json.dumps(config))
    monkeypatch.setattr(worker, "stream_factory", forbidden)
    with pytest.raises(FileExistsError):
        worker.process(*args, 4)


def test_pre_activation_raster_rejected(tmp_path, monkeypatch):
    args = setup(
        tmp_path,
        "live",
        address="00:11:22:33:44:55",
        device_id="ab" * 16,
        live_after_ns=time.time_ns() + 10**9,
    )
    monkeypatch.setattr(worker, "stream_factory", forbidden)
    with pytest.raises(ValueError, match="Pre-activation"):
        worker.process(*args, 4)
    assert not (tmp_path / "jobs").exists()


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"XRGB" + bytes(8),
        b"ZRGB" + struct.pack(">II", 9000, 13500),
        b"ZRGB" + struct.pack(">II", 64, 96) + bytes(7),
    ],
)
def test_bad_raster_has_no_transport_or_claim(tmp_path, monkeypatch, payload):
    args = setup(tmp_path)
    args[1].write_bytes(payload)
    monkeypatch.setattr(worker, "stream_factory", forbidden)
    with pytest.raises(ValueError):
        worker.process(*args, 4)
    assert not (tmp_path / "jobs").exists()


def test_wrong_media_is_not_squeezed(tmp_path):
    args = setup(tmp_path, size=(100, 100))
    with pytest.raises(ValueError, match="aspect ratio"):
        worker.process(*args, 4)


def test_landscape_page_is_rotated_to_portrait(tmp_path):
    args = setup(tmp_path, size=(96, 64))
    code, record = worker.process(*args, 4)
    assert code == 0 and record["source_size"] == [64, 96]


def test_input_outside_private_incoming_rejected(tmp_path):
    args = setup(tmp_path)
    renamed = tmp_path / "elsewhere.rgb"
    args[1].rename(renamed)
    with pytest.raises(ValueError, match="configured incoming"):
        worker.process(args[0], renamed, args[2], 4)


@pytest.mark.parametrize(
    "extra", [{"mode": "unknown"}, {"schema": 2}, {"address": "00:11:22:33:44:55"}]
)
def test_bad_config(tmp_path, extra):
    args = setup(tmp_path)
    config = json.loads(args[0].read_text())
    config.update(extra)
    args[0].write_text(json.dumps(config))
    with pytest.raises(ValueError):
        worker.process(*args, 4)


def test_worker_disconnect_keeps_receipt_and_raw(tmp_path, monkeypatch):
    class Broken(SimulatedStream):
        async def open(self):
            raise OSError("radio unavailable")

    monkeypatch.setattr(worker, "stream_factory", lambda *args: Broken)
    args = setup(tmp_path, "simulated")
    code, record = worker.process(*args, 4)
    assert code == 3 and record["state"] == "stopped"
    assert "radio unavailable" in record["error"]
    assert args[1].exists()
    with pytest.raises(FileExistsError):
        worker.process(*args, 4)
