"""Check published offline artifacts against hashes and original Android vectors."""

import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "python-render"))
from compare import without_icc  # noqa: E402
from PIL import Image  # noqa: E402

p = ROOT / "package"
m = json.loads((p / "manifest.json").read_text())
r = json.loads((p / "comparison.json").read_text())
for name, digest in {**m["sha256"], **r["files"]}.items():
    assert hashlib.sha256((p / name).read_bytes()).hexdigest() == digest, name
for name in ("source.png", "python.png", "android.png", "android-photofix.png"):
    with Image.open(p / name) as im:
        assert im.size == (768, 1152)
        assert (
            im.convert("RGB").tobytes()
            == Image.open(p / "source.png").convert("RGB").tobytes()
        )
assert (p / "python.jpg").read_bytes() == without_icc((p / "android.jpg").read_bytes())
t = json.loads((p / "transaction-android.json").read_text())
assert t["transmitted"] is False
assert bytes.fromhex(t["start"]) == b"\x0c\x01" + struct.pack(
    "<I", (p / "python.jpg").stat().st_size
)
assert bytes.fromhex(t["properties"]) == b"\x30\x34\x12\x03\x01\x01\x0dSELECT-CAL-01"
assembled = b""
for c in t["chunks"]:
    msg = bytes.fromhex(c["message"])
    assert msg[:2] == b"\x0e\x07"
    assert c["confirmedOffset"] == len(assembled)
    assert len(msg[2:]) == c["payloadLength"]
    assembled += msg[2:]
assert assembled == bytes(range(17))
assert t["decodedCompletion"] == {"handle": 7, "status": 2, "received": 17, "total": 17}
assert t["dropJob"] == "323412" and t["listJobs"] == "2c"
print(
    "Package hashes, exact raster/JPEG comparison, and Android serialization vectors passed."
)
