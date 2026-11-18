# Bounded clock-sync and full BLE preflight session — 2026-11-18

This follow-up uses the installed Select Probe Build 16 from source base
`c156228`. The preceding [physical validation](PHYSICAL_VALIDATION.md) reached
status in both native BLE contexts but correctly refused readiness for
clock-invalid flag `0x00000001`.

The user authorized one explicit clock/time-zone synchronization, followed by
read-only main-app and Share preflights, Share dismissal/relaunch and report
export. The physical session is bounded to approximately 10–15 minutes, starting
at **17:49:29 UTC** with a latest physical-test stop of **18:04:29 UTC**.
The final Share Done action visibly returned to Photos at approximately
**18:04:05 UTC**; the session was confirmed ended by **18:04:16 UTC**, an upper
bound of **14 minutes 47 seconds**. No additional printer test followed.
Documentation and verification of saved evidence followed the physical bound.

BLE printing remains unconditionally disabled. This session does not authorize
a print permit, print-job allocation, image upload, print, pairing reset or
other printer-setting writes. The clock action is the one deliberate write;
the preflights and lifecycle checks that follow remain read-only.

**Both new native BLE contexts passed full strict readiness checks, including
the previously unreached queue-list and counter queries.** The fresh Share
presentation also passed after dismissal, and all requested report exports were
actually retrieved and inspected. No print, image upload or print-job allocation
was performed.

## Observations

The explicit clock action was acknowledged, and its automatic External Accessory
read-only preflight passed. **Flags were already zero before the clock write and
remained zero afterward.** This session therefore does not establish that this
write cleared the earlier clock-invalid flag. The cause of the change from the
earlier Build 16 observations is not known.

| Check | Current result |
|---|---|
| Explicit clock synchronization and flag verification | Acknowledged; flags before 0, after 0 |
| Full native BLE preflight — main app | Passed twice through queue/counter completion |
| Full native BLE preflight — Share extension | Full strict preflight passed; actual export retrieved |
| Share dismissal and fresh relaunch | Fresh passive presentation and explicit full rerun passed |
| Main/Share report export | Both actual exports retrieved and reviewed; exact reports committed |

## Clock action and exported application report

The existing main-app action used the External Accessory lifestyle session. It
started at **17:53:44 UTC**, acknowledged and verified the clock at
**17:53:48 UTC**, and completed its automatic full read-only accessory preflight
at **17:53:49 UTC**. One time/time-zone write sent epoch **1795024427** and UTC
offset **-28800 seconds**. The report confirms flags before 0 and after 0;
there is no new 1→0 clearance claim or independent current-clock readback.

The following accessory preflight reported firmware `G1L1FA2105AR`, 100% battery,
idle/empty queue, no flags, not paused, maximum message 1000, setup byte 33,
job-name limit 16, **13 pages** and **2 calibration cycles**. Combined clock and
preflight application counts were TX 121 / RX 506 bytes, with both streams opened.
These are the legacy accessory path's counts, not native BLE packet counts.

The app's `Documents/probe.txt` was actually retrieved using Apple's device tool
into an ignored local build file. Its [sanitized exact excerpt](evidence/2026-11-18-clock-sync-report.txt)
is committed separately from the manually transcribed Mirroring observations.
Earlier discovery/accessory-name lines and the friendly-name session-attempt line
were omitted; the retained log lines are unchanged. Both raw-export and sanitized
excerpt hashes are recorded in the structured evidence. No raw device identity,
private screenshot or photo is published.

## Full native BLE preflight — main app

The main app completed two full strict preflights, with explicit requests at
**17:54:54** and **17:54:57 UTC** and successful completion at **17:54:56** and
**17:54:59 UTC**, respectively. Two sequential explicit taps were made while
the Mirroring display lagged; this was not an automatic retry. Each run opened
both virtual streams after BLE negotiation and reached the final queue/counter
checks and successful readiness result.

Both reported firmware `G1L1FA2105AR`, 100% battery, idle/empty queue, no flags,
not paused, maximum message 1000, setup byte 33, name limit 16, **13 pages** and
**2 calibration cycles**. Identity was discovered; no saved job was bound and
no print authorization was created. The page/calibration snapshots matched the
post-clock accessory preflight and each other. There was no pre-clock counter
baseline in this session.

Per-run counts were virtual TX/RX **86/469 bytes**, two opened streams; GATT TX
queued/acknowledged **46/46 bytes**, **12** successful write callbacks and GATT
RX **431 bytes**; protocol MTU **514**, ACK period **0**. Despite the report's
“GATT packets” label, queued/acknowledged/RX are byte counters in the source;
they are not counts of packets. Callback counts are recorded separately.

The [exact native main-app report](evidence/2026-11-18-main-ble-preflight-report.txt)
was exported through Share → Save to Files → iCloud Drive and its actual synced
bytes were retrieved into an ignored build file. Privacy inspection found no
device/routing identity, raw identity frames, local candidate name, account data
or photo metadata. The committed file is byte-for-byte identical to that export;
its SHA-256 is recorded in the structured evidence. This is exported application
log evidence, not a raw Bluetooth capture.

## Full native BLE preflight — Share extension

The Share extension's explicit native preflight request at **17:58:24 UTC**
opened both virtual streams that second and completed successfully at
**17:58:25 UTC**. It reached the final queue/counter checks with the same reported
firmware, 100% battery, idle/empty queue, zero flags, pause state, limits and
**13-page / 2-calibration** counters as the main-app runs.

Counts also matched: virtual TX/RX **86/469 bytes**, two streams; GATT TX queued
and acknowledged **46/46 bytes**, **12** write callbacks, RX **431 bytes**,
protocol MTU **514**, ACK period **0**. No raw power-state value is claimed from
this successful-summary report. Identity was discovered, without a saved job
binding or print authorization.

The [exact Share report](evidence/2026-11-18-share-ble-preflight-report.txt)
was exported through Save to Files to iCloud Drive using **Keep Both**, preserving
the earlier main report. The actual synced `text 2.txt` bytes were retrieved into
an ignored local build file. Privacy inspection found the same nonidentifying
report boundary as the main export; the committed file is exact and unredacted.
Its SHA-256 is recorded in the structured evidence.

## Share dismissal and relaunch

At approximately **17:59:55 UTC**, the agent tapped Run again and immediately
used Back. The UI returned to Prepare photo, then Done visibly returned to Photos
at **18:00:16 UTC**. This exercised the actual dismissal route, rather than only
backgrounding the host.

The third attempt's report was not retained/exported, so the record does not
claim an established mid-exchange cancellation or radio teardown. The read-only
exchange may have completed before dismissal. No cancellation packet counts or
zero-transmission claim is made.

Share was invoked again at approximately **18:00:50 UTC**. At approximately
**18:01:20 UTC**, the new BLE screen showed Ready for an explicit scan/preflight,
with no selected firmware, previous result or automatic UI activity. A new scan
was explicitly requested at approximately **18:01:25 UTC**. This verifies a fresh
extension presentation and state reset; it is not a cold-process-kill test or a
raw-radio inactivity capture.

The new explicit preflight request at **18:02:14 UTC** opened both virtual streams
at **18:02:15 UTC** and completed successfully at **18:02:16 UTC**. It again
reported the same firmware/readiness/limits, **13 pages / 2 calibration cycles**,
virtual TX/RX **86/469 bytes**, GATT queued/acknowledged **46/46 bytes**, **12**
write callbacks, RX **431 bytes**, MTU **514** and ACK period **0**. The fresh
presentation required a new explicit scan, identity check and preflight; it did
not reuse the previous selected-identity UI state or automatically restart.

The [exact fresh-Share rerun report](evidence/2026-11-18-share-relaunch-ble-preflight-report.txt)
was also exported to Files; actual synced `text 3.txt` bytes were retrieved,
privacy-reviewed and committed without redaction, with the hash recorded in the
structured evidence. Thus the report-export test produced actual inspectable
logs for main, first Share and fresh Share, alongside the sanitized clock log.

The final Back/Done actions visibly returned to Photos at approximately
18:04:05 UTC, and the session was confirmed over by 18:04:16 UTC. Those observations
close the bounded session; no cold-process termination or captured physical radio
disconnect is inferred from closing the extension UI.

## Evidence and privacy boundaries

No source code changed during this session. The unchanged strict BLE preflight
and UI suite was recompiled and rerun offline: **3,010 checks passed**, including
12 packet/ACK/callback combinations, 11 packet boundaries with three lifecycle
interruption modes each, explicit UI actions/generations, privacy filtering,
deadlines, late callbacks and the unconditional native-submission guard. Those
simulated checks used no physical Bluetooth device and remain distinct from the
phone observations above.

An on-screen report observed through iPhone Mirroring is a manual transcription,
not an exported application log or an over-the-air capture. In this session,
actual report bytes were also retrieved and inspected as described above. Merely
seeing a phone file-save confirmation would not establish that stronger evidence.

Only sanitized evidence may be committed. Do not publish phone screenshots,
photo-library images, device/peripheral UUIDs, addresses, serials, canonical
printer identity, installation identifiers, account details or photo metadata.
The legacy clock-sync diagnostic report may contain accessory metadata and must
be reviewed before any export is copied into repository evidence. Native BLE
reports intentionally omit routing/device identities and raw identity frames.

Application packet counters are not raw GATT/HCI captures. Internal virtual
HP+ stream counts and native GATT packet counts remain distinct. A successful
readiness result does not authorize printing or establish BLE image transfer,
physical output, sustained throughput, never-paired onboarding or App Store
eligibility. Counter snapshots must be reported only if actually queried.

Structured results are in
[2026-11-18-clock-sync.json](evidence/2026-11-18-clock-sync.json).
