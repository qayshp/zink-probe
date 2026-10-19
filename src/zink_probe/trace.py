"""Private, append-only JSONL trace with immediate flush for interrupted probes."""

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path


class Trace:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.file = os.fdopen(fd, "w")

    def event(self, event, **data):
        record = {
            "time": datetime.now(UTC).isoformat(),
            "monotonic": time.monotonic(),
            "event": event,
            **data,
        }
        self.file.write(json.dumps(record) + "\n")
        self.file.flush()

    def frame(self, transport, direction, data, layer="wire"):
        self.event(
            "frame",
            transport=transport,
            direction=direction,
            layer=layer,
            hex=bytes(data).hex(),
            length=len(data),
        )

    def close(self):
        self.file.close()
