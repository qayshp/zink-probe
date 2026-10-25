"""Prepare a local image and fit/fill preview bundle. No printer access."""

import argparse
import hashlib
import json
import os
from pathlib import Path


def _html(selected, quality, subsampling):
    # All interpolated values are validated enumerations/integers, never source
    # names, EXIF, ICC text, or user paths. No remote resources or scripts.
    return f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Select image preview</title>
<style>
body{{font:17px system-ui,sans-serif;background:#f0f2f5;color:#17202d;max-width:1050px;margin:32px auto;padding:0 20px}}
h1{{font-size:28px}} .grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}}
figure{{margin:0;padding:18px;background:white;border:1px solid #ccd2da;border-radius:12px}}
img{{display:block;width:100%;height:auto;border:1px solid #ccd2da;box-sizing:border-box}}
figcaption{{margin-bottom:14px}} h2{{margin:0 0 6px;font-size:21px}}
@media(max-width:600px){{.grid{{grid-template-columns:1fr}}}}
</style>
<h1>Select image preview</h1>
<p>Selected: <strong>{selected.upper()}</strong> · JPEG quality {quality} · {subsampling} · 768 × 1152</p>
<p>Both previews show decoded JPEG pixels. Fit keeps the whole image with white padding;
fill centers and crops it to cover the canvas. These are digital previews, not a prediction of paper color or edge trimming.</p>
<div class="grid">
<figure><figcaption><h2>Fit</h2>Whole image, centered on white.</figcaption><img src="fit-preview.png" alt="Fit JPEG preview"></figure>
<figure><figcaption><h2>Fill</h2>Full canvas, with a centered crop.</figcaption><img src="fill-preview.png" alt="Fill JPEG preview"></figure>
</div>
<p><a href="image.jpg">Selected JPEG</a> · <a href="preview.png">Selected decoded preview</a> ·
<a href="raster.png">Selected pixels before JPEG compression</a> · <a href="manifest.json">Preparation details</a></p>
<p>Everything was prepared locally. Nothing was sent to a printer.</p>
</html>
"""


def write_bundle(destination, results, options):
    """Create a new private directory; never overwrite any existing output."""
    destination = Path(destination)
    selected = results[options.mode]
    files = {
        "image.jpg": selected.jpeg,
        "raster.png": selected.raster_png,
        "preview.png": selected.preview_png,
        "fit-preview.png": results["fit"].preview_png,
        "fill-preview.png": results["fill"].preview_png,
        "preview.html": _html(
            options.mode, options.quality, options.subsampling
        ).encode(),
    }
    manifest = {
        "schema_version": 1,
        "offline": True,
        "selected_mode": options.mode,
        "variants": {mode: result.manifest for mode, result in results.items()},
        "files": {
            name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in files.items()
        },
    }
    files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    destination.mkdir(mode=0o700)  # Parent must exist; existing output is an error.
    created = []
    try:
        for name, data in files.items():
            path = destination / name
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
            with os.fdopen(fd, "wb") as file:
                file.write(data)
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        try:
            destination.rmdir()
        except OSError:
            pass  # Never remove someone else's file after an unexpected collision.
        raise
    return manifest


def add_arguments(parser):
    parser.add_argument("input", type=Path, help="Single-frame JPEG or PNG")
    parser.add_argument(
        "output", type=Path, help="New output directory; must not already exist"
    )
    parser.add_argument("--mode", choices=("fit", "fill"), default="fill")
    parser.add_argument(
        "--quality", type=int, default=90, help="JPEG quality 1..100 (default 90)"
    )
    parser.add_argument(
        "--subsampling", choices=("4:2:0", "4:2:2", "4:4:4"), default="4:2:0"
    )


def run(args):
    try:
        from .images import PreparationOptions, prepare_comparison
    except ImportError:
        print(
            json.dumps(
                {
                    "ok": False,
                    "offline": True,
                    "error": "Image preparation requires zink-probe[images] (Pillow with LittleCMS).",
                }
            )
        )
        return 1
    try:
        options = PreparationOptions(args.mode, args.quality, args.subsampling)
        if args.output.exists():
            raise FileExistsError(
                "Output directory already exists; choose a new directory"
            )
        results = prepare_comparison(args.input, options)
        manifest = write_bundle(args.output, results, options)
        encoding = manifest["variants"][options.mode]["encoding"]
        print(
            json.dumps(
                {
                    "ok": True,
                    "offline": True,
                    "output": str(args.output),
                    "selected_mode": options.mode,
                    "encoding": encoding,
                    "preview": str(args.output / "preview.html"),
                },
                indent=2,
            )
        )
        return 0
    except (OSError, ValueError, KeyboardInterrupt) as exc:
        print(
            json.dumps(
                {"ok": False, "offline": True, "error": f"{type(exc).__name__}: {exc}"}
            )
        )
        return 130 if isinstance(exc, KeyboardInterrupt) else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
