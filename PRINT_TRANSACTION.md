# Select print transaction: offline trace and driver implications

2026-10-22. Scope: Android Sprocket 3.0.2921.1 / 74251, Select/GRAND_BAHAMA's
HPLPP path. This is a static end-to-end trace of app behavior, supplemented by
execution of original serializers and transfer bookkeeping on synthetic data.
**No print transaction was sent to a printer.** There is no physical verification
of upload, queue execution, cancellation, or paper completion.

The [calibration package](experiments/calibration/README.md) contains a known
JPEG and its original-Android comparison. Source fingerprints are in
[the source index](experiments/calibration/package/source-index.json). All class
paths below are relative to the locally decompiled `sources/` root; vendor code
is not copied into the public repository. The original base APK SHA-256 is
`6395bd47fa7c669dd5fbc4a5408a4d54dd8c1841e8581be898f3bf90caaa405c`.

## Lifecycle, with evidence boundaries

1. **Session/setup.** HPLPPClient/MessageClient establish a controller using the
   supported Bluetooth transport; connection and interface setup negotiate limits.
   `MessageClient.runSetup` checks MAC cache, reads identity/features (using cached
   capabilities when the version matches), validates user color, allocates job
   color, and queues clock setting. These app setup operations are not all pure
   reads and are not automatically requirements for a minimal driver. Our existing
   read-only probe already validates discovery/identity/status on this Select;
   this offline run did not invoke setup or connect. Firmware-transfer coexistence
   is a separate branch: `print()` can pause an active firmware transfer before
   printing. A future first-print implementation should exclude that situation.
2. **Prepare and queue locally.** BasicPrintService/PreprocessPrintService produce
   the 768 × 1152 quality-90 JPEG. `QueueService.sendQueueItem` reads that local
   file, constructs SprocketPrintParameters and sets submission timestamp from
   the queued item's creation time. PrintFileTransferAction invokes client.print;
   HPLPPClient reaches MessageClient.print. The ordinary QueueService path thus
   has a timestamp and ordinarily needs job properties, even for a single copy.
3. **Preflight.** `noFirmwareTransferPrint` temporarily blocks queue polling,
   constructs IMAGE transfer state, builds optional properties when copies >1,
   timestamp is present, or allocated job color exists, then reads supported status
   fields. StatusAndErrorResolver checks print status, battery, and system flags;
   a blocking error prevents the normal start path. No claim is made that this
   alone handles every firmware error or remote-queue race.
4. **Create job.** `noErrorSendPrint` sends PrintStart and receives a file handle
   plus job ID. It emits onPrintJobCreated. The job ID is assigned by the device,
   not a locally invented ID. This step itself is a state mutation and is not a
   safe live probe merely because no JPEG bytes have followed yet.
5. **Set properties.** If transfer properties exist, update their job ID and send
   WriteJobProperty; await its response before starting file data. If absent,
   proceed directly to file data. Copy count is always serialized when this
   message is present; color/name/time/URL are conditional. No DPI, heater-count,
   feed-speed, or crop-position property appears in this inspected message format.
6. **Upload sequential chunks.** `sendWriteMessage` sets maximum payload to the
   negotiated target message size minus 2 bytes (opcode and handle). The first
   chunk starts at zero. FileWrite responses drive subsequent chunks: status 1
   confirms an **absolute received position**, then the next slice starts there.
   HPLPPTransferInfo.confirmPage assigns the value; it does not add it. Each final
   slice is min(packet size, remaining bytes). The target's total-length field is
   decoded/logged, but this callback does not use it as a digest or verification.
7. **Upload completion.** FileWrite status 2 marks transfer complete, updates
   progress, unblocks queue polling, and emits PRINT_TRANSFER completion. The app's
   file-transfer listener sets its item to **SENT**, not PRINTED. There is no separate
   image-file CRC/commit/end request in this traced upload path. Firmware CRC/apply
   code is a different branch and must not be borrowed for image jobs.
8. **Conditional queue activation — important Select-specific app behavior.**
   QueueService's completion listener calls `kickIdleRemoteQueue`. Its model list
   explicitly includes GRAND_BAHAMA. If not already kicked, not resuming, and not
   hardware-paused, it clears the local pause state, sends RESUME action if ACTIONS
   is supported, calls hardwareResume, and restarts status polling. Hardware resume
   uses SetOptionsAction to set PAUSE_PRINTING=false when supported; otherwise it
   proceeds locally. Thus “no final commit in the transfer callback” does **not**
   mean the full app sends nothing after upload. Whether either resume operation
   is actually required on this firmware remains physically untested. Do not
   automatically unpause other users' jobs in a future driver.
9. **Observe actual job lifecycle.** MessageClient schedules queue polling at
   1000 ms intervals when enabled/unblocked. It lists jobs, reads properties for
   newly seen jobs, then reads status/current job. Empty/populated queues permit
   another upload; PAUSED is handled distinctly. QueueService.syncLocalJobs maps
   the current job to PRINTING unless blocked, and reconciles remote membership.
   A transmitted job disappearing from the queue is not treated uniformly: a SENT
   job enters a disappeared-items map (1000 ms TTL, then removal), while other
   transmitted states can reach doPostPrintActivities/PRINTED. This is host-side
   inference, not an explicit printer receipt proving a sheet was successfully
   ejected. A new driver should preserve unknown/cancelled/error outcomes rather
   than equating upload completion or queue disappearance with successful output.
10. **Cancel/failure.** deleteQueueJob sends DropJob for a specific assigned ID.
    Errors in start/properties/upload are reported and queue polling is unblocked
    on the relevant failure paths. FileWrite status 3 is cancelled (IMAGE branch
    reports failure); other non-1/non-2 states also fail. Physical cancellation
    timing, partially consumed paper, retained handles, and reconnect/resume
    behavior are untested. Never blindly repeat a start after an ambiguous timeout:
    the first request might already have created a job.

## Resolved application message layouts

All multibyte integers below are little-endian. Bytes are hexadecimal. These are
application messages, not BLE fragments or RFCOMM envelopes.

| Operation | Request | Successful response / interpretation |
| --- | --- | --- |
| Read status | `08 <supported tags>` | `09 <typed fields>`; flags, print state, battery, progress, job ID, battery state, queue, hosts |
| PrintStart | `0c 01 <JPEG byte length:u32>` | `0d <file handle:u8> <job ID:u16>` |
| WriteJobProperty | `30 <job ID:u16> 03 <copies:u8> [fields]` | `31` |
| FileWrite | `0e <file handle:u8> <JPEG chunk bytes>` | `0f <handle:u8> <status:u8> <received:u32> <total:u32>` |
| ListJobs | `2c` | `2d <zero or more job IDs:u16>`; no count prefix |
| ReadJobProperty | `2e <job ID:u16> <requested field IDs>` | `2f <typed property response>` |
| DropJob | `32 <job ID:u16>` | `33` |
| Resume action | `38 01 00` | `39`; action ID 1, not an image-data command |
| Clear hardware pause | `1c 04 00` (single-field form) | `1d`; actual SetOptionsAction may serialize other populated options |
| Protocol error | — | `01 <failed opcode> <error code>` |

Property IDs: 01 name (variable-length UTF-8), 02 RGB label (3 bytes), 03 copies
(u8), 04 submission time (u32 epoch seconds: Java milliseconds divided by 1000), 05 auxiliary
URL (variable-length UTF-8). These properties are job metadata, not raster geometry.
FileWrite statuses: 1 OK/continue, 2 complete, 3 cancelled, 4 failed.
PrintStart maps errors 8 and 12 to cannot-accept-job/remote-queue-busy.

Controller recognizes protocol error 18 (hex 12) as RETRY and permits up to five
retries with count×100 ms delays. MessageQueueItem's default response timeout is
5000 ms. The decompiler produces awkward duplicated control-flow in Controller's
listener: these constants/conditions are visible, but no callback retry/error
state machine was executed here. Do not generalize protocol-directed RETRY to
retrying arbitrary transport timeouts. Runtime recovery tests remain future work.

RFCOMM wraps messages in `HP+`, length-type byte, little-endian length, then the
message. The Android transport supports byte/short/int length widths; a typical
1000-byte application chunk needs the short-length envelope. BLE adds its own
fragment sequencing/acknowledgement. Neither transport framing nor MTU is the JPEG
pixel geometry. The current diagnostic RFCOMM encoder is deliberately limited to
small allowlisted requests; it is **not** an upload implementation.

## Offline original-class execution

The new permission-free `transactionOnly` harness mode instantiated only message
objects, SprocketByteBuffer and HPLPPTransferInfo. It did not create a controller,
printer client, device, or transport. The retained synthetic vectors establish:

- Our 139,679-byte Python chart length serializes to `0c019f210200`.
- Job 0x1234, one copy, name SELECT-CAL-01 serializes to
  `3034120301010d53454c4543542d43414c2d3031`.
- A 17-byte sequence 00..10 with maximum 8-byte payload produces chunks of 8, 8,
  and 1 bytes at confirmed offsets 0, 8, and 16, with handle 7.
- The synthetic completion payload decodes handle=7, status=2, received=17,total=17.
- getProgress returns approximately 0.47058824 at 8/17 and 0.9411765 at 16/17.
  This corrects a misleading integer-looking division in the decompiled Java.
- ListJobs serializes to `2c`; DropJob(0x1234) to `323412`.

These are original compiled-class observations, not proof that a physical Select
will accept those synthetic values. `verify_package.py` independently checks the
vectors, exact JPEG length and chunk reconstruction. At a *hypothetical* negotiated
application limit of 1000, this JPEG needs 140 chunks with at most 998 JPEG bytes
per request (last payload 957). A driver must use the actual negotiated limit.
No executable uploader or expanded probe write allowlist was added.

## What this contributes to a driver

High value: deterministic prepared image, known JPEG parameters, negotiated chunk
sizes, absolute acknowledgement offsets, assigned job IDs, conditional properties,
upload-versus-print distinction, Select's queue activation branch, and conservative
failure/reconciliation behavior. These are actionable even if heater count stays
unknown. A useful driver can hand firmware a correct JPEG without reconstructing
its thermal firing algorithm.

Remaining physical questions: acceptance of the independent JPEG; actual need and
ordering of resume operations; queue/cancel behavior under disconnects; reliable
completion evidence; geometric mapping/clipping. Firmware scheduling, line-firing
frequency, native dot pitch, heater count, and thermal-energy control are not
resolved by this APK path. The calibration package is ready for a later separately
authorized print, but this trace is not sufficient to claim a tested print driver.
