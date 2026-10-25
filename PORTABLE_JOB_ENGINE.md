# Portable single-job engine

Updated 2026-10-25. The `zink_probe.jobs` library runs without native Bluetooth or
image-processing dependencies on macOS, Linux, and Windows. It implements
preflight, one job allocation, job properties, sequential JPEG upload, status
observation, durable local records, and read-only reconciliation. A deterministic
simulated printer exercises the byte-stream boundary. This is the shared engine
milestone from [the driver roadmap](DRIVER_ROADMAP.md).

**One physical photo through the Windows adapter and OS print queue now passes.**
The [first Windows print report](examples/windows-print-queue/FIRST_PRINT.md)
records quality 100 / 4:4:4, complete upload acknowledgement, printing observed,
a one-page counter increment, idle completion and the user's confirmation of
the sheet. Physical printing through the macOS/Linux adapters remains unvalidated.
The [Linux socket adapter](LINUX_ADAPTER.md) is implemented with read-only BlueZ
preflight, real-socket simulation and ARM64 host tests. Two live read-only
connections to the Select passed after pairing; [hardware evidence](experiments/linux-adapter/README.md)
records the initial pairing issue and successful checks. The [Windows adapter](WINDOWS_ADAPTER.md)
passes simulated jobs, native ARM64 Windows interface tests and two real
read-only Select connections; its [hardware evidence](experiments/windows-adapter/README.md)
records successful inspection/reconnection after ordinary Windows pairing.
The [macOS stream adapter](experiments/macos-adapter/README.md) now passes real
read-only checks and simulated jobs through its native callback facade. Physical
printing through this adapter/engine combination remains untested.
The existing macOS diagnostic command retains its deny-by-default write policy.
`zink-simulate` uses only the simulated printer; `zink-macos-check` opens real
read-only sessions. Physical CAL-02 and CAL-03 were sent with their separately
bounded experimental senders, not the new library.

## Use without a printer

Install the portable core and test tools with Python 3.11 or later:

```sh
python -m pip install -e '.[dev]'
zink-simulate experiments/jpeg-quality/q100-444-optimized.jpg \
  --journal logs/simulated-jobs.sqlite \
  --name SELECT-CAL-03 --allow-alternative-sampling --encoder-quality 100
python -m pytest -q
```

The simulator reports `simulated: true`, the local and remote job IDs, final
state, acknowledged bytes, encoding metadata, and whether reconstructed upload
bytes equal the input. It writes a local journal and never opens Bluetooth or a
network connection. Each invocation creates a new local UUID for its simulated
job. macOS hardware diagnostics now install with `.[macos,dev]`; hardware
dependencies have moved into the `macos` optional dependency group.

## Interfaces and responsibilities

| Component | Responsibility |
|---|---|
| `JobSpec` | Immutable JPEG bytes, local UUID, name, copy count, payload hash, inspected sampling and declared encoder-quality metadata |
| `UploadPlan` | Deterministic application messages and strict acknowledgement validation; one outstanding mutation |
| `FramedSession` | HP+ framing over an injected async byte stream, response deadlines, target-event separation, poisoned-session handling |
| `JobJournal` | SQLite claims, committed request intents, acknowledged state, observations and history |
| `JobEngine` | Fresh identity/capability/status preflight, upload orchestration and conservative completion |
| `SimulatedPrinter` | In-memory protocol peer with chunk fragmentation, events and injected failure behavior; not a firmware emulator |

The supplied stream implements `async write(bytes)`, `async read(maximum)`, and
`async close()`. The macOS adapter uses asynchronous native open/write callbacks
with bounded waits and documents the synchronous API-entry/close-call limits.
Adapters must treat write exceptions as possibly
having transmitted bytes. The engine owns and closes the supplied session.
Framing and application policy remain separate: the job session is explicit,
while ordinary probe transports still reject PrintStart, FileWrite, job-property
writes, resume and cancellation commands.

Example use with the simulated peer:

```python
import asyncio
from pathlib import Path
from zink_probe.jobs import FramedSession, JobEngine, JobJournal, JobSpec
from zink_probe.jobs.simulator import DEVICE_ID, SimulatedPrinter

async def example():
    job = JobSpec(
        Path("experiments/calibration/package-v2/python.jpg").read_bytes(),
        name="SELECT-CAL-02", copies=1, encoder_quality=90,
    )
    printer = SimulatedPrinter(read_size=17, write_fragment=3)
    with JobJournal("logs/example-jobs.sqlite") as journal:
        engine = JobEngine(
            FramedSession(printer), journal, DEVICE_ID, poll_interval=0,
        )
        result = await engine.run(job)
        print(result)

asyncio.run(example())
```

A real adapter must use the selected printer's protocol-reported device ID,
not the simulator's constant or a macOS-only BLE UUID. The engine checks the
Select model and exact expected device ID again after connecting.

## Preflight and encoding policy

Before allocating a remote job, the engine checks negotiated message length,
required capabilities, JPEG file type, name/copy properties, the advertised
UTF-8 name byte limit, an unpaused configuration, an idle empty queue, zero
system flags, battery state, and page/calibration counters. The initial battery
threshold is 30%, matching the bounded calibration experiments. Unsupported or
missing information produces `not_submitted` without a print mutation.

The **16-byte advertised name limit** on the tested Select matters. The first
CAL-03 name was 22 bytes and was rejected; the new engine tests ASCII and
multibyte UTF-8 names against the limit before PrintStart. It also checks whether
the entire property message fits the negotiated application limit.

The core accepts prepared 768×1152, eight-bit, three-component baseline JPEGs.
Its header inspector extracts sampling and whether quantization tables are all
ones. It does not perform full entropy decoding or replace image preparation.
Callers must fully decode/validate prepared images upstream. An encoder quality
number is recorded as declared metadata: JPEG does not carry a universal quality
number, and it is not a heater or feed-speed setting.

4:2:0 remains the default accepted sampling. 4:4:4 and horizontal 4:2:2 require
explicit `allow_alternative_sampling=True`. The quality-100 4:4:4 CAL-03 file now
has [one physical success on the FA unit](experiments/calibration/CAL03_PRINT.md).
4:2:2 remains unprinted. This opt-in prevents silently changing the compatibility
default or implying broad support across units and firmware builds. JPEG quality
100 still does not mean lossless. Copy counts 1..255 are serialized and tested in
simulation; physical evidence covers one copy per job only.

## Persistence and duplicate prevention

Each job has a local UUID distinct from the printer-assigned job ID. The journal
stores the payload SHA-256, length, encoding, requested copies/name, expected
device identity, baseline counters, assigned handle/ID, last acknowledged offset,
and state history. It does not store image bytes. Use a private local directory;
new database files request POSIX mode 0600, while Windows uses the containing
directory's ACL. The existing diagnostic trace mode test is consequently POSIX
specific rather than treating Windows mode bits as ACL verification.

SQLite uses `synchronous=FULL`. Before **each** mutating request, a transaction
commits its opcode, length, hash and starting offset. Only a validated reply
advances the acknowledged offset or phase. A crash between sending and recording
the reply therefore leaves a conservative pending request. A journal write
failure before dispatch prevents that request from being sent.

The local UUID cannot be submitted twice. A unique database index also permits
only one unresolved claim per device within that journal. A second process using
the same database is covered; a different computer or database is not. Retain
the database after an interrupted job. Deleting it removes these local safeguards.
This is **not** an exactly-once guarantee across Bluetooth disconnects or hosts.

| State | Meaning |
|---|---|
| `not_submitted` | Preflight failed before a persistent submission claim or print mutation |
| `claimed` | Local claim exists; no mutation is yet durably marked pending |
| `request_pending` | Intent committed; transmission/acknowledgement may be incomplete |
| `accepted` | PrintStart acknowledged with a remote ID and handle |
| `uploading` | Properties acknowledged and/or chunks being acknowledged |
| `uploaded` | FileWrite status 2 acknowledged the complete payload |
| `printing` | Status identified this remote job as printing |
| `completed` | The device observations satisfy the conservative criteria below |
| `rejected` | A matching explicit PrintStart rejection; no remote job acknowledged |
| `stopped` | Explicit rejection after allocation; the claim remains unresolved |
| `uncertain` | Timeout, disconnect, cancellation, malformed response, storage problem or insufficient completion evidence |

`completed` and `rejected` release the per-device active-claim constraint; the
UUID remains permanently used. Other outcomes retain the claim. No automatic
retry, reconnect, cancellation, queue clearing, pause clearing, or resume command
is implemented. Even the protocol's RETRY error stops the job. The CAL-03
experiment's manually selected, trace-gated recovery is **not** a library policy.

## Completion and read-only reconciliation

Upload completion never counts as physical completion. The engine requires:

- The full upload was acknowledged.
- This exact assigned job was observed in printing state.
- Two observations show idle state, zero flags, no current job, and an empty
  job list and queue.
- The page-counter increase equals the requested copy count and the calibration
  count is unchanged.
- No foreign queued/current job or contradictory counter change was observed.

An observation timeout or contradiction leaves `uncertain`. Contradictory
samples are retained and permanently block automatic completion attribution for
that job, including after process restart; a later idle reading cannot erase them.
A constant zero progress percentage does not imply a stall; both actual sheets showed that
behavior. These observations are separate requests, not an atomic snapshot.
Counters and status are indirect evidence; `physical_ejection_confirmed` remains
false in the library result. User observation confirmed the actual CAL-03 sheet.

After an interruption, construct a new session and call
`await engine.reconcile(local_id)`. It performs identity/status/job/counter reads
only. It can establish completion when a fully acknowledged job previously seen
printing later returns idle with matching counters. It never reconstructs an
unknown job ID, resends data, or reuses an upload handle. If the final upload
acknowledgement was lost, the current policy remains uncertain even if later
observations look promising. Manual investigation can use the retained history.

An external client could perform activity between polls; the protocol provides
no authenticated per-page completion receipt. The engine cannot guarantee
attribution across unobserved external jobs or job-ID reuse over long periods.

## Verification and CI

The tests reconstruct both committed calibration payloads, compare the new plan
against every upload acknowledgement from the successful CAL-03 trace, verify
copy/name serialization, and exercise fragmented/coalesced frames and unsolicited
events. Failure cases include wrong identity/model, paused/occupied queues,
invalid UTF-8 name length, lost replies, wrong handles/offsets/totals, premature
completion, rejected properties, protocol RETRY, write failure after remote
acceptance, a single optional empty final chunk, cancellation, database failure,
restart, competing local claims, counter changes, foreign jobs, and disappearance
without completion evidence. Imports are tested with native Bluetooth modules
explicitly forbidden.

The first Windows CI run exposed a test-discovery portability issue: pytest's
automatic parameter ID contained the entire truncated JPEG and exceeded Windows'
32,767-character environment-variable limit. Explicit short case IDs preserve
the same test input and assertions while allowing that case to execute there.
The second run exposed an overly short 150 ms test-only completion deadline on
a slower Windows runner. Ordinary simulator cases now allow ten seconds;
intentional timeout cases retain their short deadline. The engine's three-minute
default and full durable writes are unchanged.

[The CI workflow](.github/workflows/ci.yml) runs Python 3.11 and 3.14 on Ubuntu,
macOS and Windows: six combinations. It installs the portable package, image extra and
test tools, runs lint and the full test suite, checks the bounded calibration
transcripts, simulates the exact quality-100 CAL-03 payload, and builds a wheel.
It follows the [GitHub Python matrix workflow guidance](https://docs.github.com/en/actions/tutorials/build-and-test-code/python).
Action revisions are pinned to commits verified from their official repositories.
Native callback-facade tests run on all runners; macOS also checks the real PyObjC
delegate buffer metadata without opening Bluetooth.
Live results are available in [GitHub Actions](https://github.com/qayshp/zink-probe/actions/workflows/ci.yml).

CI establishes software behavior on those runners. It does not validate their
Bluetooth stacks, pairing, printer communication or paper output. Separate local
read-only validation covers the macOS, Linux and Windows adapters. [General image preparation](IMAGE_PREPARATION.md) is implemented.
The [unified preparation/status/submission CLI](UNIFIED_CLI.md) is implemented; physical printing
through the new adapters requires separate authorization and validation.
OS queue/IPP/PAPPL integration is later work.
