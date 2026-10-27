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
2. Physically validate the read-only preflight below over iOS, then bind a fresh
   preflight result to the saved job identity before any submission.
3. Integrate the durable TrackedUpload wrapper below with one persistent store.
   Do not bypass it by using a fresh bare UploadPlan after a crash.
4. The framed exchange below is connected only to read-only preflight. Integrate
   it with tracked upload only after the remaining submission gates are met.
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

## Build 7: read-only preflight and framed accessory exchange

`ReadOnlyPreflight` checks firmware, Select model 0x48d3, 16-byte protocol identity,
connection-local message limit/security, required requests/MIME/job properties,
job-name limit, pause configuration, battery/power, idle/error-free status, empty
queue and page/calibration counters. Capability JSON and binary TLV encodings,
paged capability downloads and paged metrics have explicit limits. Unknown,
missing, malformed, incompatible or busy states fail closed. Only pause config
is needed for eligibility; unrelated LED and sleep settings are not queried.

The fixed request sequence is 04/01, 04/09, 04/06, 24/0010, 2a, discovered-handle
28 reads, 1a/04, selected 08 status fields, 2c and dataset-1 3a pages. There is no
PrintStart, FileWrite, job-property write, settings write or interface-selection
command. Connection setup 0x24 negotiates a session-local limit; it is not a
persistent printer-setting change. The desktop RFCOMM 0x0a/02 interface selector
is deliberately not copied onto iAP, whose interface-selection semantics remain
unverified. A setup rejection stops the experiment instead of trying alternatives.

`AccessoryExchange` encodes HP+ requests with 1/2-byte lengths, accepts bounded
1/2/4-byte reply lengths, handles partial/zero writes and fragmented replies,
and refuses oversized, concatenated, unsolicited or malformed frames. It has a
10-second monotonic deadline and terminal cancellation/error state, with no retry
or resynchronization. The main app's StreamDelegate owns actual InputStream and
OutputStream calls, closes both streams on all exit paths, and bounds the whole
preflight to 60 seconds/256 KiB received. Lifecycle closure remains enforced by
the app. RX logs omit raw preflight frames containing identity information.

The main app adds **Run read-only preflight** for HPISPSLE/lifestyle. The first
successful diagnostic discovers the device ID; subsequent runs in the same app
process compare it. This in-memory pin is not durable job identity. A future job
must supply its saved expectedDeviceID and perform fresh checks; a diagnostic
success is not a print authorization. Firmware must also match accessory metadata.
The upload/journal code remains unlinked from both app targets. The Share extension
continues to prepare/export offline and cannot submit a print.

Local tests cover JSON/TLV success, every response split and length encoding,
partial/zero/failed writes, premature input, deadlines, cancellation at every
request-byte offset, malformed/rejected replies at each stage, wrong identity,
busy/low-battery/error states, missing capabilities, multi-page replies and loops.
The core is compiled into the signed iPhone app. Installation and user-observed
physical preflight results are separate evidence; no physical preflight result
is assumed from offline tests or successful installation.

### Build 8 setup validation correction

The user's Build 7 report at 2026-10-27 04:39:36 UTC (October 26 locally)
passed firmware, model and device-ID reads, then stopped on a 9-byte framed
setup reply. Total RX was 61 bytes and TX was 29. Because Build 7 omitted raw
setup bytes, the iOS setup value itself is not established by this report.

The zero-only final-byte check was an implementation mistake: previously saved
successful FA desktop sessions report maximum 1000 and final byte 33 (0x21).
Build 8 accepts this observed value as well as the synthetic zero fixture,
preserves it as `setupSecurityRaw`, and includes it in successful summaries.
Its semantics remain opaque; this is not an authentication bypass or a claim
that iOS necessarily returned 0x21. Other values still stop, now with the
non-identifying setup payload in the error. A regression test uses the observed
payload `25 e8 03 21` and continues the simulated preflight to completion.
No printer commands beyond the existing read-only sequence were added.

### Build 9 status refusal diagnostics

The user's Build 8 run at 2026-10-27 04:43:04 UTC passed identity, setup,
capability discovery/download and pause checks, then refused the status snapshot
with `Printer not idle/empty/error-free`. RX=337 bytes, TX=62 bytes. The snapshot
values were omitted, so the report does not establish whether flags, printer
state, current job or queue caused refusal. It does not prove a paper fault or a
busy printer. No job-list or counter queries were reached on this run.

Build 9 preserves the same eligibility rules and request sequence, but includes
all six non-identifying status values in readiness and battery refusal messages.
A regression test checks the reported fields and terminal refusal. No attempt is
made to clear flags, modify state or weaken the guard. Physical iOS full-preflight
success remains unverified pending a complete run.

### Physical Build 9 result: clock-validity flag

User report, 2026-10-27 04:44:41 UTC (October 26 Pacific): accessory remained
visible and the user ran preflight directly without the picker. Identity, setup,
capabilities and pause checks passed. The status snapshot was:

- flags `0x00000001`: bit 0, named Time invalid by the inspected HP library;
- printer state 1: idle; current job 0; queue state 1: empty;
- battery 61%; power state 1: in use.

The only failing readiness condition was the zero-flags requirement. This is not
evidence of paper trouble, print activity or a Bluetooth failure. It also does not
establish that the printer would reject a print with this flag set: that has not
been tested. List-jobs and metrics were not reached (RX 337, TX 62 bytes).
The same time-invalid flag was previously observed in desktop read-only probes;
see INVESTIGATION.md and VALIDATION.md. SETTINGS_RESEARCH.md records that the
inspected Android setup path sends a clock-setting request, but this iOS probe
has not done so. No automatic clock setting or readiness-rule relaxation was made.
The next useful read-only improvement is to separate diagnostic collection from
submission eligibility, allowing queue/counter reads to finish while reporting
this flag as a readiness blocker. That is proposed, not implemented here.
