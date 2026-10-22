"""Verify CAL-02 source geometry, repeat controls, and Android comparison evidence."""

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

P = Path(__file__).resolve().parent / "package-v2"
m = json.loads((P / "manifest.json").read_text())
r = json.loads((P / "comparison.json").read_text())
for name, h in {**m["sha256"], **r["files"]}.items():
    assert hashlib.sha256((P / name).read_bytes()).hexdigest() == h, name
im = Image.open(P / "source.png").convert("RGB")
assert im.size == (768, 1152)
for group in ("gray", "lines", "edge"):
    patches = [p for p in m["patches"] if p.get("group") == group]
    assert len(patches) == 3
    arrays = [np.array(im.crop(p["box_exclusive"])) for p in patches]
    assert all(np.array_equal(arrays[0], a) for a in arrays)
for p in m["patches"]:
    x0, y0, x1, y1 = p["box_exclusive"]
    assert 0 <= x0 < x1 <= 768 and 0 <= y0 < y1 <= 1152
assert len(m["crop_gauges"]) == 28
assert len(r["cases"]) == 6
assert all(
    c["processDataMatches"]
    and c["python_vs_android_bitmap"]["pixel_exact"]
    and c["jpeg_equal_except_icc"]
    for c in r["cases"]
)
print(
    "CAL-02 hashes, source repeat equality, patch bounds, crop gauges, and all six Android comparisons passed."
)
