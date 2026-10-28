# Offline iOS submission tests

Run from the repository root on macOS with Xcode's Swift toolchain:

```sh
mkdir -p build
swiftc ios/PrintCore/*.swift ios/coordinator-tests/main.swift -o build/ios-coordinator-tests
build/ios-coordinator-tests
```

No simulator, phone, Bluetooth connection or printer is used. The tests generate
an sRGB baseline JPEG through ImageIO and a temporary SQLite journal. The peer
parses actual HP+ output frames and returns framed synthetic protocol replies.
Writes/reads are deliberately fragmented; the harness supplies monotonic virtual
time so timeouts run without sleeping.

Coverage includes:
- Normal and empty-final uploads, exact uploaded JPEG comparison and two distinct
  successful jobs with permanent protection against reusing either local job ID.
- Full preflight eligibility; wrong identity, pause and clock-invalid refusal before
  PrintStart. Completion needs our job's printing state, final upload acknowledgement,
  one page increment, unchanged calibration count and two idle observations.
- Lost start/property/chunk/final replies, foreign jobs, extra pages, changed
  calibration count, invalid offsets and missing processing evidence.
- Cancellation at request boundaries and disconnection at all 12 byte boundaries
  of the first mutating HP+ frame; no later writes after a terminal result.
- Abrupt child-process exits while PrintStart is pending, immediately after upload,
  and after a printing observation. Recovery reads only, never uploads or prints.
- Injected SQLite update failures, migration of an older three-column journal,
  competing coordinator claims, permanent contradictory-attribution blocks and
  firmware changes during recovery.
- JPEG truncation, wrong dimensions, progressive frame marker and EXIF rotation.

The simulated peer is intentionally narrow and is not a firmware emulator. These
checks establish local sequencing and duplicate safeguards, not physical iOS print
compatibility, real transfer timing or survival of Share-extension termination.
The existing journal tests separately exercise nine abrupt process-exit points,
competing process claims and a corrupt database. The existing framing and Python
upload-parity suites remain part of CI.
