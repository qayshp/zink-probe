"""Send synthetic PDFs through a verified Linux CUPS capture queue, never hardware."""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from smoke import attribute, exchange


def command(*args):
    return subprocess.check_output(args, text=True, env={**os.environ, "LC_ALL": "C"})


def require(condition, message):
    # These guards must remain active even if Python is launched with -O.
    if not condition:
        raise ValueError(message)


def validate(root, queue, service, port, output):
    root = root.resolve()
    config = json.loads((root / "config.json").read_text())
    require(
        config["mode"] == "capture"
        and not config.get("address")
        and not config.get("device_id"),
        "Requires capture mode without a printer address or identity",
    )
    require(Path(config["data_dir"]).resolve() == root, "Capture data path mismatch")
    uri = f"ipp://127.0.0.1:{port}/ipp/print"
    require(
        command("lpstat", "-v", queue).strip() == f"device for {queue}: {uri}",
        "CUPS queue does not target the expected local capture service",
    )
    pid = int(
        command("systemctl", "--user", "show", service, "--property=MainPID", "--value")
    )
    argv = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
    require(
        len(argv) >= 7
        and argv[2] == str(root / "config.json").encode()
        and argv[6] == str(port).encode(),
        "Running service does not use the capture configuration",
    )
    require(
        not command("lpstat", "-W", "not-completed", "-o", queue).strip(),
        "CUPS capture queue must be idle",
    )
    initial_jobs = set((root / "jobs").iterdir())
    for job in initial_jobs:
        receipt = json.loads((job / "result.json").read_text())
        require(
            receipt["state"] == "captured" and not receipt["bluetooth_opened"],
            "Existing worker must have a completed capture receipt",
        )
    initial_raw = len(list((root / "incoming").glob("*.rgb")))
    job_query = attribute(0x44, "which-jobs", "all") + attribute(
        0x44, "requested-attributes", "job-state"
    )
    status, values = exchange(port, 10, attrs=job_query)
    assert status < 0x100
    initial_states = [int.from_bytes(x, "big") for x in values.get("job-state", [])]
    require(all(state >= 7 for state in initial_states), "Capture service must be idle")
    output.mkdir(parents=True)
    font = ImageFont.load_default(size=32)
    images = []
    for size in ((768, 1152), (1152, 768)):
        image = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((12, 12, size[0] - 13, size[1] - 13), outline="black", width=3)
        draw.text((36, 40), "LINUX CAPTURE ONLY", fill="black", font=font)
        for i, color in enumerate(("red", "lime", "blue")):
            draw.rectangle((36 + i * 180, 110, 190 + i * 180, 310), fill=color)
        images.append(image)
    submitted = []
    for name, image, landscape in (
        ("portrait", images[0], False),
        ("landscape", images[1], True),
        ("two-page", images[0], False),
    ):
        path = output / f"{name}.pdf"
        image.save(
            path,
            resolution=768 * 25.4 / 58,
            quality=100,
            save_all=name == "two-page",
            append_images=[images[0]] if name == "two-page" else [],
        )
        request = command(
            "lp",
            "-d",
            queue,
            "-n",
            "1",
            "-t",
            f"Zink capture {name}",
            "-o",
            "media=58x87mm.Borderless",
            "-o",
            "print-scaling=fit",
            "-o",
            "print-quality=5",
            "-o",
            f"orientation-requested={4 if landscape else 3}",
            str(path),
        )
        submitted.append(request.strip())
        expected = len(submitted)
        for _ in range(180):
            status, values = exchange(port, 10, attrs=job_query)
            assert status < 0x100
            states = [int.from_bytes(x, "big") for x in values.get("job-state", [])]
            if len(states) == expected + len(initial_states) and all(
                s >= 7 for s in states
            ):
                break
            time.sleep(0.25)
        else:
            raise TimeoutError(f"Native capture did not finish {name}")
        receipts = [
            json.loads(p.read_text())
            for p in (root / "jobs").glob("*/result.json")
            if p.parent not in initial_jobs
        ]
        assert len(receipts) == min(expected, 2)
        assert all(
            r["state"] == "captured" and not r["bluetooth_opened"] for r in receipts
        )
        assert states.count(8) == initial_states.count(8) + (
            1 if name == "two-page" else 0
        ), states
    assert len(list((root / "jobs").iterdir())) == len(initial_jobs) + 2
    assert len(list((root / "incoming").glob("*.rgb"))) == initial_raw + 1
    assert not (root / "jobs.sqlite").exists() and not list(root.rglob("frames.jsonl"))
    cups_states = []
    for request in submitted:
        job_id = int(request.split()[3].rsplit("-", 1)[1])
        for _ in range(120):
            status, values = exchange(
                631,
                9,
                resource=f"/printers/{queue}",
                attrs=attribute(0x21, "job-id", job_id)
                + attribute(0x44, "requested-attributes", "job-state"),
            )
            assert status < 0x100
            state = int.from_bytes(values["job-state"][0], "big")
            if state >= 7:
                break
            time.sleep(0.25)
        else:
            raise TimeoutError("CUPS job did not reach a terminal state")
        cups_states.append(state)
    report = {
        "queue": queue,
        "mode": "capture",
        "cups_submissions": submitted,
        "native_job_states": sorted(states),
        "cups_job_states_in_submission_order": cups_states,
        "rejection_visible_as_cups_failure": cups_states[-1] in (7, 8),
        "preexisting_captures": len(initial_jobs),
        "preexisting_native_jobs": len(initial_states),
        "receipts": receipts,
        "two_page_rejected_before_worker": True,
        "bluetooth_opened": False,
        "cups_status": command("lpstat", "-W", "all", "-l", "-o", queue),
    }
    (output / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--queue", default="HP_Sprocket_Select_Preserve_Edges_Capture")
    parser.add_argument(
        "--service", default="zink-select-preserve-edges-capture.service"
    )
    parser.add_argument("--port", type=int, default=8632)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    validate(args.root, args.queue, args.service, args.port, args.output.resolve())
