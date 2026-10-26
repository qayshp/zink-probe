"""Cancel a native POSIX capture job with a deliberately stalled fake worker.

The replacement worker records its PID and waits; it cannot access Bluetooth.
This exercises native cancellation, termination and reaping without a printer.
"""

import argparse
import io
import json
import os
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image
from smoke import attribute, exchange, wait_job


def run(executable, root, ignore_term=False):
    root.mkdir(parents=True)
    for name in ("incoming", "spool"):
        (root / name).mkdir()
    (root / "config.json").write_text(
        json.dumps({"schema": 1, "mode": "capture", "data_dir": str(root)})
    )
    marker = root / "worker.pid"
    fake = root / "fake_worker.py"
    fake.write_text(
        "import os, signal, time\nfrom pathlib import Path\n"
        + ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\n" if ignore_term else "")
        + f"Path({str(marker)!r}).write_text(str(os.getpid()))\n"
        + "time.sleep(120)\n"
    )
    wrapper = root / "fake-python"
    wrapper.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(fake))} "$@"\n'
    )
    wrapper.chmod(0o700)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [
            str(executable),
            str(wrapper),
            str(root / "config.json"),
            str(root / "incoming"),
            str(root / "spool"),
            str(root / "bridge.log"),
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid = None
    try:
        for _ in range(40):
            if process.poll() is not None:
                raise RuntimeError((root / "bridge.log").read_text())
            try:
                assert exchange(port, 11)[0] == 0
                break
            except OSError:
                time.sleep(0.25)
        else:
            raise TimeoutError("Capture listener did not start")
        source = io.BytesIO()
        Image.new("RGB", (64, 96), (40, 100, 160)).save(source, format="JPEG")
        status, values = exchange(
            port,
            2,
            attrs=attribute(0x49, "document-format", "image/jpeg"),
            payload=source.getvalue(),
        )
        assert status < 0x100, (status, values)
        job_id = int.from_bytes(values["job-id"][0], "big")
        for _ in range(80):
            if marker.exists() and marker.read_text():
                pid = int(marker.read_text())
                break
            time.sleep(0.1)
        else:
            raise TimeoutError("Fake worker did not start")
        started = time.monotonic()
        status, values = exchange(port, 8, attrs=attribute(0x21, "job-id", job_id))
        assert status < 0x100, (status, values)
        assert wait_job(port, job_id) == 7  # canceled, never completed/replayed
        elapsed = time.monotonic() - started
        assert elapsed < 6, elapsed
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pid = None
        else:
            raise AssertionError("Canceled worker was not reaped")
        assert len(list((root / "incoming").glob("*.rgb"))) == 1
        assert not list(root.rglob("result.json"))
        report = {
            "state": "canceled",
            "worker_reaped": True,
            "worker_ignored_sigterm": ignore_term,
            "cancel_seconds": round(elapsed, 3),
            "raw_retained": True,
            "bluetooth_opened": False,
            "worker": "fake sleeper; no protocol or printer access",
        }
        (root / "cancel-result.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))
    finally:
        if pid is not None:
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass
        process.terminate()
        process.wait(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if sys.platform == "win32":
        parser.error("POSIX cancellation test requires macOS or Linux")
    for ignore in (False, True):
        run(
            args.executable.resolve(),
            args.output.resolve() / ("forced" if ignore else "graceful"),
            ignore,
        )
