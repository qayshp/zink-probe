"""Bounded CAL-03 payload, exact one-copy transcript, and no-retry checks."""

import struct
import unittest

from print_cal03 import CLAIM, NAME, PAYLOAD, Cal03Plan

from zink_probe.protocol import ProtocolError


class Cal03Tests(unittest.TestCase):
    def test_exact_payload_and_one_copy(self):
        data = PAYLOAD.read_bytes()
        plan = Cal03Plan(data, 1000)
        self.assertEqual(
            plan.next_message(), b"\x0c\x01" + struct.pack("<I", len(data))
        )
        with self.assertRaises(ProtocolError):
            plan.next_message()
        plan.accept(b"\x0d\x03\x0d\x00")
        self.assertEqual(
            plan.next_message(), b"\x30\x0d\x00\x03\x01\x01" + bytes([len(NAME)]) + NAME
        )
        plan.accept(b"\x31")
        received, chunks = b"", 0
        while plan.state != "complete":
            message = plan.next_message()
            self.assertLessEqual(len(message), 1000)
            self.assertEqual(message[:2], b"\x0e\x03")
            received += message[2:]
            chunks += 1
            plan.accept(
                b"\x0f"
                + struct.pack(
                    "<BBII",
                    3,
                    2 if len(received) == len(data) else 1,
                    len(received),
                    len(data),
                )
            )
        self.assertEqual(received, data)
        self.assertEqual(chunks, 152)
        with self.assertRaises(ProtocolError):
            plan.next_message()

    def test_pin_and_separate_claim(self):
        with self.assertRaises(ProtocolError):
            Cal03Plan(PAYLOAD.read_bytes() + b"x", 1000)
        self.assertEqual(CLAIM.name, "cal03-one-print-attempt.json")


if __name__ == "__main__":
    unittest.main()
