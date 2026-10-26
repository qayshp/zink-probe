# Swift upload core — offline milestone

This is the first native Swift print-transaction component for eventual iOS
Share-sheet printing. It ports the payload sequencing in
`src/zink_probe/jobs/model.py::UploadPlan`. It is deliberately **not included in
either app target** and has no ExternalAccessory, network or Bluetooth dependency.
The installed/deployable Share extension remains offline preparation only.

Implemented:
- One-copy PrintStart (0x0c), job properties (0x30), FileWrite (0x0e).
- UTF-8 job-name byte limits, variable-length name encoding, little-endian fields.
- Negotiated payload limit capped at the desktop core's 4096 bytes.
- One outstanding request; exact acknowledgement handle, total and absolute offset.
- Optional single empty final chunk, with no repeated-final loop.
- Terminal stop on rejected/malformed replies or explicit transport-failure stop.
- `uploaded` means acknowledged transfer, never physical print completion.

Tests generate golden **payloads**, not HP+ frames, from the existing Python
implementation and compare every Swift request. Synthetic JPEG-envelope bytes
isolate sequencing; they are not printable fixtures. Limits 32, 255, 4096 and
8192 (clamped) exercise multiple chunks and both finalization paths. Tests cover
UTF-8, invalid inputs, zero job ID, bad opcode/handle/status/offset/total, truncated
replies, remote rejection, interruption, duplicate send and repeated empty final.
Local Swift tests passed; this suite is included in iOS CI.

## Remaining gates before any live submission

1. Validate the prepared baseline JPEG completely before constructing a plan.
   This core only checks size and envelope; it is not a JPEG validator.
2. Port the desktop read-only preflight: Select identity, firmware, capabilities,
   negotiated limits, queue, battery, error state and pause configuration.
3. Add durable job intent and pending-request journaling **before** transmission.
   A new in-memory instance does not prevent duplicate jobs after a crash.
4. Add HP+ framing, bounded incremental parsing and partial stream writes, with
   timeout/cancellation tests. Connect to ExternalAccessory only after these gates.
5. Observe completion conservatively and reconcile ambiguous jobs read-only.
6. Decide lifecycle ownership: extensions can be terminated; do not assume they
   can finish a Bluetooth transfer in the background. Start with an explicit
   foreground confirmation flow, and test interruption before enabling printing.

A successful offline transcript does not prove iOS print commands are accepted,
Share-extension accessory access, background execution or App Store approval.
No physical printer was accessed for this milestone. No additional print is
currently authorized.

Run from the repository root with Python 3.12 or newer (or the project venv):

```sh
mkdir -p build
PYTHONPATH=src python3 ios/print-tests/generate.py build/ios-upload-fixtures.json
swiftc ios/PrintCore/UploadPlan.swift ios/print-tests/main.swift -o build/ios-upload-tests
build/ios-upload-tests build/ios-upload-fixtures.json
```
