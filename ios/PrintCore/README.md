# Swift upload core — offline milestone

This is the first native Swift print-transaction component for eventual iOS
Share-sheet printing. It ports the payload sequencing in
`src/zink_probe/jobs/model.py::UploadPlan`. The core has no ExternalAccessory,
network or Bluetooth dependency. Build 12 includes it in the app and Share targets
for an explicitly confirmed **simulation-only** flow; no native submission writer
is connected. The extension's separate firmware-read experiment is unchanged.

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

## Current submission status

The complete offline coordinator is implemented below. Its prepared-image validator,
preflight, journal, framed upload and completion/recovery paths run together against
an in-memory printer. Build 12 links the coordinator, upload and journal into the
app and Share extension, with an immutable review and explicit confirmation screen.
`SimulatedSubmission` owns a fixed in-memory peer: it accepts no transport or writer
from the UI. Its writes cannot reach the independent read-only accessory probe.
Their physical connection/read tests are documented separately. A future live
integration still needs real-device binding, durable storage/lifecycle ownership
and a native stream owner. No real iOS print submission is enabled.

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

The initial journal milestone intentionally had **no claim-release API** (superseded
by verified completion in the coordinator below). Even an acknowledged
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
iOS file-protection configuration and real app/extension lifecycle ownership remain
integration work. Build 12's simulation journal is not the future live job store.

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
At Build 7 the upload/journal code was unlinked from both app targets. Build 12
links it only to the memory simulation described below. Real submission remains
disabled in the Share extension.

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

### Build 10 explicit clock synchronization

A separate **Sync clock, verify, then preflight** action validates the Select model,
reads system flags, sends exactly one SET_TIME request (0x18), requires its 0x19
acknowledgement, and reads flags again. The time payload matches the inspected
Android setup path: unsigned 32-bit Unix seconds plus signed 32-bit current UTC
offset in seconds, both little-endian. Timestamp/offset are sampled when preparing
the write, not when opening the session. Other flags block the write. Verification
requires the time-invalid bit to clear and other flag bits to remain unchanged.
If verification succeeds, the existing read-only preflight runs automatically.
There is no print, automatic clock retry or clock write in the read-only button.
The shared 60-second run bound and 10-second exchange deadlines still apply.
A lost acknowledgement is reported as failure; the write may have taken effect.
There is no identified current-clock readback command; status verification cannot
measure clock drift, exact accuracy or retention across power loss.

Offline tests pin the exact seconds/negative-timezone bytes, validate the before
and after flags, reject uncleared/other flags and malformed/rejected responses,
and stop after interruptions at each stage. Signed build passed. Physical flag
clearance and the subsequent preflight remain pending the user's report.

Desktop audit: macOS/Linux/Windows use the same Python JobEngine. It reads
system_flags and requires zero in idle(); it does not ignore time_invalid. No
clock write currently occurs in the portable job engine. A normal setup sync is
recommended after this explicit physical test, separate from read-only probes;
it has not been added to desktop adapters in this change.

### Physical Build 10 success: clock sync and complete iOS preflight

User-supplied report: 2026-10-27 05:14:19–05:14:20 UTC (October 26,
22:14:19–22:14:20 America/Los_Angeles). The Select was already visible.
The explicit clock action received its acknowledgement and verified flags
changing from 1 to 0. Sent epoch: 1793078059; UTC offset: -25200 seconds.
The subsequent read-only preflight completed successfully on HPISPSLE,
firmware G1L1FA2105AR, hardware 4138, lifestyle protocol:

| Observation | Result |
| --- | --- |
| Battery | 72% |
| Printer/queue | Idle, empty; no current job |
| Flags / pause | Zero flags; not paused |
| Negotiated maximum | 1000 payload bytes |
| Setup raw byte | 33 (0x21), now observed on iOS too |
| Job-name limit | 16 UTF-8 bytes |
| Page / calibration counters | 13 / 2 |
| Combined application TX / RX | 121 / 506 bytes |

This physically validates explicit clock synchronization, flag clearance and
the complete bounded preflight through our independent iOS accessory connection.
The counter values are a snapshot, not proof of unchanged counters across this
run (no pre-sync counter baseline was taken). Timestamp resolution is one second;
the log is not a precise latency benchmark. Raw frames were omitted, so this is
application-validated summary evidence, not a new raw-frame fixture.

No print was sent. A discovered identity is not yet bound to a durable job; this
was the first successful preflight in that app process. Clock accuracy/drift,
power-cycle retention, actual iOS uploads/printing, and Share-extension transport
lifecycle remain unverified. No further device action was performed while
recording the user's result.


## Complete offline submission coordinator

`PreparedJobImage` accepts an immutable encoded JPEG after bounded header checks,
ImageIO decoding, complete source status, baseline/8-bit/three-component checks,
768×1152 dimensions, supported chroma sampling, sRGB and upright-orientation checks.
It accepts quality-100 4:4:4 output and does not resize or recompress it. ImageIO
acceptance is not a proof of arbitrary JPEG entropy correctness or printer support
for every possible encoder output. Existing PhotoPreparation supplies the normal
prepared image; the coordinator receives its JPEG through this validator.

`SubmissionCoordinator` is a serial, event-driven state machine: call `write`,
`receive`, `tick`, `cancel` or `disconnected` with monotonic time. It has no native
transport dependency or automatic retry. `write` invokes a supplied byte-writer;
partial/zero writes stay within one exchange. `terminal` tells the future owner
when to close both native streams. No raw upload-plan restoration exists.

The normal path:
1. Reject a previously used local job ID or an unresolved device claim.
2. Run fresh full read-only preflight against the explicitly expected protocol ID.
3. Construct one-copy tracked upload with negotiated message/name limits.
4. Commit a device claim and baseline page/calibration/firmware evidence before
   generating the first mutating request. Every pending mutation is committed before
   any corresponding frame bytes reach the writer.
5. Validate acknowledgements through upload completion, preserving JPEG bytes exactly.
6. Observe status, queue and paginated counters. Completion requires the matching
   printer job to have been seen printing, a durable final upload acknowledgement,
   exactly one added page, unchanged calibration count and two consecutive idle/empty
   snapshots with zero flags. `physicalEjectionConfirmed` remains false.

Page-counter reset/extra pages, calibration changes, foreign job IDs, errors or
unknown states prevent attribution. Contradictory observations set a durable block.
Disappearance alone never completes a job. Exchange deadlines are ten seconds;
the default overall coordinator bound is 300 seconds, with two-second observation
spacing. Tests use virtual time and zero spacing to run without real sleeps.

The recovery initializer takes a saved local ID and its journal, not image bytes.
It rechecks identity/firmware and observes read-only. It cannot create an UploadPlan
or send PrintStart/properties/FileWrite. Missing remote IDs/baselines or a recorded
attribution block refuse recovery. Lost final acknowledgement remains uncertain,
even if later snapshots suggest a page printed. There is no blind retry or manual
"clear and resend" action. Explicit clock sync remains a separate action; a clock-
invalid preflight fails before claiming or sending a print job.

### Journal evolution and duplicate boundaries

The journal retains all local IDs. Only coordinator-verified `completed` records
release the active device constraint so another distinct job can run. Upload,
rejection, timeout and uncertain states remain blocking. Migration from the older
three-column table preserves every record and keeps legacy claims active. SQLite
FULL transactions and an active-device unique index arbitrate multiple processes.
Two coordinators may preflight simultaneously; only one can claim/send a job.

The store holds fingerprints, counters and state, not the user's image. Recovery
therefore cannot resend even by accident. Use one stable journal path and canonical
protocol device ID. Another host/database, deleting app data, or bypassing this core
still defeats local duplicate prevention. This is not a printer-side exactly-once
contract. Build 12 adds confirmation UI for simulation. App Group access, file
protection, real-device confirmation and native transport ownership remain
live-integration work. Build 11's physical connection evidence remains separate.

### Offline verification

The framed simulated peer supplies identity, setup, binary capabilities, configuration,
status, queue, counters and upload acknowledgements. It collects and compares the
full JPEG, exercises fragmented reads/writes and backpressure, and simulates printing
then counter advancement. It is a deterministic peer, not firmware emulation.

Tests cover real sRGB JPEG input, malformed/truncated input, complete one-copy jobs,
one-byte transport fragments, optional empty final, permanent local-ID rejection,
release only after verified completion, concurrent coordinator claims, wrong printer,
paused/clock-invalid preflight, lost start/properties/chunk/final acknowledgements,
missing processing evidence, foreign jobs, extra pages, calibration changes, bad
offsets, cancellation at request boundaries and every first-mutation frame byte
offset. Child processes exit abruptly while start is pending, after upload and after
printing is observed; reopened recovery sends only reads and never resubmits.
Injected database failures prevent mutation, and legacy migration preserves claims.
The earlier journal process-death and framing regression suites remain enabled.

```sh
swiftc ios/PrintCore/*.swift ios/coordinator-tests/main.swift -o build/ios-coordinator-tests
build/ios-coordinator-tests
```

Local suites passed; CI now runs the integrated suite and typechecks all core sources
against the iOS SDK. No physical printer connection or paper was used for these tests.

Integrated test source and run instructions: [coordinator tests](../coordinator-tests/README.md).

## Build 12: confirmed Share-flow simulation

The Share extension now reuses `SimulationPhotoFlow`: prepare one image, tap
**Review simulated job**, inspect the frozen image/settings, then explicitly tap
**Confirm simulated job**. There is no automatic submission when sharing, preparing
or opening review. The review includes destination, one-copy count, layout, quality,
768 × 1152 dimensions, exact JPEG bytes and sampling. The JPEG is copied by value
into the review, then validated without recompression before submission.

`SimulatedSubmission` is an actor that serializes the full coordinator, SQLite
journal, virtual monotonic clock and framed in-memory peer. It has no backend
selector, native stream, writer callback or ExternalAccessory dependency. Its
simulated success, lost-final-reply and interrupted-upload scenarios cannot send
application bytes to a real printer. The existing manual connection screen remains
separate and can still perform only its bounded passive/firmware tests.

Each review has a stable local UUID and a distinct virtual printer ID. The simulation
store is `Application Support/SelectSimulation/SIMULATION-ONLY.sqlite` in the current
app/extension container. A repeated confirmation or reopening that saved ID cannot
replay it. A new review intentionally represents a new virtual target, so it does
not test contention between multiple reviews of the same physical printer. The
coordinator suites separately exercise same-device and cross-process contention.
There is no shared App Group, durable prepared-image handoff, saved-job browser,
automatic restart/resubmission or live queue in this UI.

Closing the confirmation, stopping the simulation or extension-host inactivity
cancels the current runner. Cancelling after a possible mutation preserves an
uncertain record and blocks another submission of that ID. Abrupt process death
leaves the coordinator's durable pending record; no automatic resume is implemented.
The optional **Check saved job read-only** action invokes the recovery initializer,
which receives no JPEG and cannot create another upload. The duplicate-check action
constructs another coordinator only to verify that the saved claim rejects it;
it never drives its writer.

Validation and remaining physical boundaries are recorded in
[Share simulation tests](../share-flow-tests/README.md).
