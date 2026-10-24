"""SQLite job claims and state history, committed before mutating requests.

One active claim per physical device within this journal. FULL synchronous
transactions preserve conservative pending states after interruption. Local
storage cannot guarantee exactly-once behavior across independent hosts/files.
"""

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class SubmissionBlocked(RuntimeError):
    pass


class JobJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        self.db = sqlite3.connect(self.path, timeout=5)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        with self.db:
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, device TEXT NOT NULL, state TEXT NOT NULL, record TEXT NOT NULL)"
            )
            self.db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS one_active_device ON jobs(device) WHERE state NOT IN ('completed', 'rejected')"
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS history (seq INTEGER PRIMARY KEY, job TEXT NOT NULL REFERENCES jobs(id), record TEXT NOT NULL)"
            )

    def get(self, local_id):
        row = self.db.execute(
            "SELECT record FROM jobs WHERE id=?", (local_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def claim(self, spec, device_id, baseline):
        record = {
            "schema": 1,
            "local_id": spec.local_id,
            "device_id": device_id,
            "sha256": spec.sha256,
            "bytes": len(spec.jpeg),
            "name": spec.name,
            "copies": spec.copies,
            "encoding": spec.encoding,
            "state": "claimed",
            "job_id": None,
            "file_handle": None,
            "acknowledged_bytes": 0,
            "seen_printing": False,
            "upload_acknowledged": False,
            "baseline": baseline,
            "pending": None,
            "error": None,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        encoded = json.dumps(record)
        try:
            with self.db:
                self.db.execute(
                    "INSERT INTO jobs VALUES (?, ?, ?, ?)",
                    (spec.local_id, device_id, "claimed", encoded),
                )
                self.db.execute(
                    "INSERT INTO history(job, record) VALUES (?, ?)",
                    (spec.local_id, encoded),
                )
        except sqlite3.IntegrityError as exc:
            raise SubmissionBlocked(
                "Job ID already used or device has an unresolved job in this journal"
            ) from exc
        return record

    def update(self, local_id, **changes):
        with self.db:
            # Acquire the SQLite writer lock before read-modify-write.
            self.db.execute("UPDATE jobs SET state=state WHERE id=?", (local_id,))
            record = self.get(local_id)
            if record is None:
                raise KeyError(local_id)
            record.update(changes, updated_at=datetime.now(UTC).isoformat())
            encoded = json.dumps(record)
            self.db.execute(
                "UPDATE jobs SET state=?, record=? WHERE id=?",
                (record["state"], encoded, local_id),
            )
            self.db.execute(
                "INSERT INTO history(job, record) VALUES (?, ?)", (local_id, encoded)
            )
        return record

    def history(self, local_id):
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT record FROM history WHERE job=? ORDER BY seq", (local_id,)
            )
        ]

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
