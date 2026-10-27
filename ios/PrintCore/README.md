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
3. Integrate the durable TrackedUpload wrapper below with one persistent store.
   Do not bypass it by using a fresh bare UploadPlan after a crash.
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

## Durable tracking and conservative recovery

`JobJournal.swift` adds SQLite-backed claims and `TrackedUpload`, which owns a
fresh upload plan. It commits the pending request's opcode and SHA-256 **before
returning bytes to the future transport**. Accepted replies save the printer job
ID, handle and acknowledged offset. Records also bind the local UUID, device
identity, JPEG hash and length. The image itself is not stored in this journal.

SQLite `BEGIN IMMEDIATE`, FULL synchronous transactions and unique local-job and
device keys serialize competing claims. Any journal/acknowledgement failure stops
the live wrapper. A lost acknowledgement remains pending or uncertain. Opening the
journal never reconstructs an upload plan or grants permission to send. Recovery
lists unresolved records and reports the recorded state; it sends nothing.

This milestone intentionally has **no claim-release API**. Even an acknowledged
upload remains blocked because physical completion is not established. A rejected
or interrupted job also remains blocked until a future read-only reconciliation
implementation and explicit resolution policy exist. Never delete a record to
"retry." Use one stable canonical device identity and one persistent journal path
for every submission. Different databases/hosts, app uninstall/storage deletion,
or direct use of the lower-level UploadPlan bypass this protection. This is not
an exactly-once guarantee from the printer. The eventual adapter must consume each
returned message once and must not retry writes after an ambiguous failure.

Instances are synchronous and serial-use; the future UI/transport owner must
serialize calls. Cross-process claims are guarded by SQLite. App Group storage,
iOS file-protection configuration and app/extension lifecycle ownership remain
integration work. No app target links the print core yet.

Validation: nine child-process abrupt exits (`_exit`, without cleanup) cover
claim, pending requests, acknowledgements and upload completion. Reopening blocks
both the same ID and a fresh ID for that device. Tests inject failed commits before
send and after acknowledgement, exercise uncertain stop, corrupt database failure,
record listing and competing process claims. Local tests and iOS SDK typechecking
passed. These tests cover process interruption, not physical power-loss testing.

```sh
swiftc ios/PrintCore/*.swift ios/journal-tests/main.swift -o build/ios-journal-tests
build/ios-journal-tests
```
