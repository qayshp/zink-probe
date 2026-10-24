"""Generate our test-only linear RGB profile from LittleCMS's sRGB primaries.

No vendor profile is embedded. Replace each RGB tone curve with gamma 1.0,
rebuild the ICC tag table, and fix the date for reproducibility. This lets tests
distinguish real color conversion from merely attaching an sRGB label.
"""

import struct
from pathlib import Path

from PIL import ImageCms


def make_profile():
    original = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    count = struct.unpack_from(">I", original, 128)[0]
    tags = []
    for i in range(count):
        signature, offset, size = struct.unpack_from(">4sII", original, 132 + i * 12)
        payload = original[offset : offset + size]
        if signature in (b"rTRC", b"gTRC", b"bTRC"):
            payload = b"curv" + bytes(4) + struct.pack(">IH", 1, 256)
        tags.append((signature, payload))
    header = bytearray(original[:128])
    header[24:36] = struct.pack(">6H", 2026, 10, 24, 0, 0, 0)
    header[84:100] = bytes(16)  # Unset optional profile ID after changing content.
    table, content = bytearray(), bytearray()
    base = 132 + 12 * count
    for signature, payload in tags:
        table.extend(struct.pack(">4sII", signature, base + len(content), len(payload)))
        content.extend(payload)
        content.extend(bytes((-len(content)) % 4))
    result = header + struct.pack(">I", count) + table + content
    struct.pack_into(">I", result, 0, len(result))
    return bytes(result)


if __name__ == "__main__":
    Path(__file__).with_name("linear-rgb.icc").write_bytes(make_profile())
