"""No hardware: verify bounded single-print framing, transcript, and failure stops."""

import json
import struct
import tempfile
import unittest
from pathlib import Path

from first_print import (
    PAYLOAD,
    PrintPlan,
    ProtocolError,
    claim_attempt,
    frame,
    idle_preflight,
)

from zink_probe.protocol import RfcommParser, validate_request


class FirstPrintTests(unittest.TestCase):
    def setUp(self):
        self.data = PAYLOAD.read_bytes()
        self.plan = PrintPlan(self.data, 1000)

    def enter_upload(self):
        self.assertEqual(
            self.plan.next_message(), b"\x0c\x01" + struct.pack("<I", len(self.data))
        )
        self.plan.accept(b"\x0d\x07\x34\x12")
        self.assertEqual(
            self.plan.next_message(), b"\x30\x34\x12\x03\x01\x01\x0dSELECT-CAL-02"
        )
        self.plan.accept(b"\x31")

    def test_full_transcript_exact_one_copy_and_payload(self):
        self.enter_upload()
        received = b""
        while self.plan.state != "complete":
            msg = self.plan.next_message()
            self.assertLessEqual(len(msg), 1000)
            self.assertEqual(RfcommParser().feed(frame(msg)), [msg])
            received += msg[2:]
            status = 2 if len(received) == len(self.data) else 1
            self.plan.accept(
                b"\x0f" + struct.pack("<BBII", 7, status, len(received), len(self.data))
            )
        self.assertEqual(received, self.data)
        with self.assertRaises(ProtocolError):
            self.plan.next_message()

    def test_lost_reply_blocks_another_start(self):
        self.plan.next_message()
        with self.assertRaises(ProtocolError):
            self.plan.next_message()

    def test_lost_chunk_reply_blocks_retransmission(self):
        self.enter_upload()
        self.plan.next_message()
        with self.assertRaises(ProtocolError):
            self.plan.next_message()

    def test_invalid_acknowledgements_stop(self):
        for handle, status, received, total in [
            (8, 1, 998, len(self.data)),
            (7, 1, 1, len(self.data)),
            (7, 2, 998, len(self.data)),
            (7, 4, 998, len(self.data)),
            (7, 1, 998, 0),
        ]:
            self.plan = PrintPlan(self.data, 1000)
            self.enter_upload()
            self.plan.next_message()
            with self.assertRaises(ProtocolError):
                self.plan.accept(
                    b"\x0f" + struct.pack("<BBII", handle, status, received, total)
                )
            with self.assertRaises(ProtocolError):
                self.plan.next_message()

    def test_rejected_start_stays_uncertain(self):
        self.plan.next_message()
        with self.assertRaises(ProtocolError):
            self.plan.accept(b"\x01\x0c\x08")
        with self.assertRaises(ProtocolError):
            self.plan.next_message()

    def test_claim_persists_and_refuses_second_attempt(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "claim.json"
            claim_attempt(p, "example")
            with self.assertRaises(FileExistsError):
                claim_attempt(p, "example")
            self.assertEqual(json.loads(p.read_text())["copies"], 1)

    def test_payload_is_pinned(self):
        with self.assertRaises(ProtocolError):
            PrintPlan(self.data + b"x", 1000)

    def test_ordinary_probe_still_rejects_print_and_resume(self):
        for msg in [
            b"\x0c\x01" + struct.pack("<I", len(self.data)),
            b"\x0e\x07x",
            b"\x30\x34\x12\x03\x01",
            b"\x38\x01\x00",
            b"\x1c\x04\x00",
        ]:
            with self.assertRaises(ProtocolError):
                validate_request(msg)

    def test_nonidle_or_occupied_preflight_refused(self):
        status = {
            "print_status_code": 1,
            "system_flags": 0,
            "queue_status_code": 1,
            "current_job_id": 0,
            "battery_percent": 99,
            "battery_status_code": 2,
        }
        cfg = {"errors": {}, "values": {"pause_printing_raw": 0}}
        idle_preflight(status, cfg, [])
        for key, value in [
            ("print_status_code", 7),
            ("system_flags", 8),
            ("queue_status_code", 4),
            ("current_job_id", 123),
            ("battery_percent", 10),
            ("battery_status_code", 4),
        ]:
            with self.assertRaises(ProtocolError):
                idle_preflight({**status, key: value}, cfg, [])
        with self.assertRaises(ProtocolError):
            idle_preflight(status, cfg, [123])
        with self.assertRaises(ProtocolError):
            idle_preflight(
                status, {"errors": {}, "values": {"pause_printing_raw": 1}}, []
            )


if __name__ == "__main__":
    unittest.main()
