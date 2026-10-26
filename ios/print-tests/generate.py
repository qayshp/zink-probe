"""Generate upload payload golden traces using the existing desktop state machine."""

import json
import struct
import sys
from types import SimpleNamespace

from zink_probe.jobs.model import UploadPlan

# Synthetic envelope isolates sequencing from image decoding, intentionally.
jpeg = b"\xff\xd8" + bytes(range(256)) * 2 + b"\xff\xd9"
cases = []
for maximum in (32, 255, 4096, 8192):
    for final in (False, True):
        plan = UploadPlan(
            SimpleNamespace(jpeg=jpeg, name="Select café", copies=1), maximum, 64
        )
        exchanges = []
        while plan.phase != "uploaded":
            request = plan.next_message()
            if request[0] == 12:
                reply = b"\x0d\x07\x34\x12"
            elif request[0] == 48:
                reply = b"\x31"
            else:
                offset = plan.offset + len(request) - 2
                complete = offset == len(jpeg) and (not final or len(request) == 2)
                reply = b"\x0f" + struct.pack(
                    "<BBII", 7, 2 if complete else 1, offset, len(jpeg)
                )
            exchanges.append({"request": list(request), "reply": list(reply)})
            plan.accept(reply)
        cases.append({"maximum": maximum, "jpeg": list(jpeg), "exchanges": exchanges})
with open(sys.argv[1], "w") as output:
    json.dump(cases, output)
