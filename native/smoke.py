"""Capture-only native IPP smoke test. No Bluetooth configuration or submission.

This tiny IPP client is test code; production HTTP/IPP/raster handling is PAPPL.
"""

import argparse
import http.client
import io
import json
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image


def attribute(tag, name, value):
    name = name.encode()
    if isinstance(value, int):
        value = struct.pack(">i", value)
    elif isinstance(value, str):
        value = value.encode()
    return (
        bytes([tag])
        + struct.pack(">H", len(name))
        + name
        + struct.pack(">H", len(value))
        + value
    )


def exchange(port, operation, *, attrs=b"", job_attrs=b"", payload=b""):
    body = struct.pack(">BBHI", 2, 0, operation, 1) + b"\x01"
    body += attribute(0x47, "attributes-charset", "utf-8")
    body += attribute(0x48, "attributes-natural-language", "en")
    body += attribute(0x45, "printer-uri", f"ipp://127.0.0.1:{port}/ipp/print")
    body += attrs
    if job_attrs:
        body += b"\x02" + job_attrs
    body += b"\x03" + payload
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    try:
        conn.request("POST", "/ipp/print", body, {"Content-Type": "application/ipp"})
        response = conn.getresponse()
        data = response.read()
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}: {data[:200]!r}")
    finally:
        conn.close()
    status = int.from_bytes(data[2:4], "big")
    values, pos, name = {}, 8, ""
    while pos < len(data):
        tag = data[pos]
        pos += 1
        if tag == 3:
            break
        if tag < 16:
            continue
        size = int.from_bytes(data[pos : pos + 2], "big")
        pos += 2
        if size:
            name = data[pos : pos + size].decode()
        pos += size
        size = int.from_bytes(data[pos : pos + 2], "big")
        pos += 2
        value = data[pos : pos + size]
        pos += size
        values.setdefault(name, []).append(value)
    return status, values


def wait_job(port, job_id):
    for _ in range(120):
        status, values = exchange(port, 9, attrs=attribute(0x21, "job-id", job_id))
        assert status < 0x100, (status, values)
        state = int.from_bytes(values["job-state"][0], "big")
        if state >= 7:
            return state
        time.sleep(0.25)
    raise TimeoutError("IPP job did not reach a terminal state")


def run(executable, root, layout="fill"):
    root.mkdir(parents=True)
    for name in ("incoming", "jobs", "spool"):
        (root / name).mkdir()
    (root / "config.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "mode": "capture",
                "data_dir": str(root),
                "preparation_mode": layout,
            }
        )
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    command = [
        str(executable),
        sys.executable,
        str(root / "config.json"),
        str(root / "incoming"),
        str(root / "spool"),
        str(root / "bridge.log"),
        str(port),
    ]
    process = subprocess.Popen(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        for _ in range(40):
            if process.poll() is not None:
                raise RuntimeError((root / "bridge.log").read_text())
            try:
                status, capabilities = exchange(port, 11)
                break
            except OSError:
                time.sleep(0.25)
        else:
            raise TimeoutError("IPP listener did not start")
        assert status == 0
        assert b"custom_58x87mm_58x87mm" in capabilities["media-supported"]
        assert capabilities["copies-supported"] == [struct.pack(">ii", 1, 1)]
        assert b"application/pdf" not in capabilities["document-format-supported"]
        image = Image.new("RGB", (64, 96), (20, 90, 180))
        source = io.BytesIO()
        image.save(source, format="JPEG", quality=100)
        outcomes = []
        for quality in (4, 5):
            status, values = exchange(
                port,
                2,
                attrs=attribute(0x49, "document-format", "image/jpeg"),
                job_attrs=attribute(0x23, "print-quality", quality),
                payload=source.getvalue(),
            )
            assert status < 0x100, (status, values)
            job_id = int.from_bytes(values["job-id"][0], "big")
            assert wait_job(port, job_id) == 9
            outcomes.append(
                {
                    "ipp_job": job_id,
                    "quality": quality,
                    "state": "completed-in-capture-mode",
                }
            )
        status, values = exchange(
            port,
            2,
            attrs=attribute(0x49, "document-format", "image/jpeg")
            + attribute(0x22, "ipp-attribute-fidelity", b"\x01"),
            job_attrs=attribute(0x21, "copies", 2),
            payload=source.getvalue(),
        )
        assert status >= 0x400, (status, values)
        receipts = [
            json.loads(p.read_text()) for p in (root / "jobs").glob("*/result.json")
        ]
        assert len(receipts) == 2 and all(
            r["state"] == "captured" and not r["bluetooth_opened"] for r in receipts
        )
        assert {r["encoding"]["sampling"] for r in receipts} == {"4:2:0", "4:4:4"}
        assert all(r["preparation_mode"] == layout for r in receipts)
        for job in (root / "jobs").iterdir():
            manifest = json.loads((job / "preparation.json").read_text())
            assert manifest["geometry"]["mode"] == layout
            assert (job / "safe-area-preview.png").is_file()
            if layout == "preserve-edges":
                assert min(manifest["geometry"]["padding_pixels"].values()) >= 48
                with Image.open(job / "image.jpg") as prepared:
                    assert prepared.getpixel((24, 576)) == (255, 255, 255)
                    assert prepared.getpixel((384, 576))[2] > 150
        assert not list(root.rglob("frames.jsonl"))
        report = {
            "native_start": True,
            "loopback_ipp": True,
            "media": "58x87mm",
            "copies_2_rejected": True,
            "jobs": outcomes,
            "bluetooth_opened": False,
            "preparation_mode": layout,
        }
        (root / "smoke-result.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    for layout in ("fill", "preserve-edges"):
        run(args.executable.resolve(), args.output.resolve() / layout, layout)
