# Milestone 1 validation

Current follow-up: [INVESTIGATION.md](INVESTIGATION.md). Historical references below
to “first-print timestamp” use the original label; the HP app artifact names it
BornOnDate and the current JSON key is `born_on_timestamp`.

## Live revalidation after the newer APK comparison — 2026-10-20

The operator confirmed the printer was on and nearby and requested live testing.
The physical condition supplied before this run was ten new ZINK sheets loaded,
with the orange calibration card already processed and discarded. This condition
is operator-reported, not a protocol-derived sheet count.

Two fresh discovery/connection sessions completed successfully over both BLE and
RFCOMM channel 2. No permission changes, re-pairing, or manual recovery were needed.
The CLI implementation was unchanged from commit `5cee79b`.

| Check | Live result |
| --- | --- |
| Model / firmware / hardware | Select `0x48D3`, submodel 3 / `G1L1FA2105AR` / `4138` |
| Identity | Identical across BLE/RFCOMM and across the two sessions |
| Protocol / feature version | 1 / 9 |
| Connection negotiation | Accepted on both; max message 1000; security byte `0x21` |
| Capability table | 227 bytes, identical across transports/sessions and to the earlier capture |
| Status observation | 12 paired samples over two minutes; all values stable and identical between transports |
| Battery | 100%, state 2 (app label: charging) |
| Printer / queue / current job | Idle / empty / zero; list-jobs response empty |
| System flags | `0x00000001`: time invalid; no unknown set bits |
| Host count | BLE initially 0; 1 with RFCOMM open, also 1 throughout observation |
| Sleep / auto-off | 3 / 60 minutes |
| LED / pause / host threshold | White RGB `[255,255,255]` / 0 / 3 |
| Configuration readback | Matched across transports, after observation, and on reconnect |
| Setup tag 13 | Raw 0 on both; newer app identifies this as setup version, with 1 its completed-onboarding marker |
| BornOnDate | Raw `1775953184`, unchanged; app displays it as First Print |
| Security mode | Raw 1, unchanged; detailed enum meaning still unresolved |
| Metrics pagination | Both pages of dataset 1 read successfully on both transports in both sessions |
| Printer pages / calibration cycles | 10 / 2 in both sessions, on both transports; unchanged from earlier research |
| Jam / out-of-paper / incorrect-paper events | All zero |
| Pages since cover open / calibration | Both zero |
| GATT / SDP discovery | GATT metadata returned; fresh SDP query succeeded in both sessions |
| Channel 1 | Six `ff550200ee10` chunks over five seconds, zero application bytes transmitted |
| Cleanup | No recorded cleanup errors in either session |

The tentative cross-device supply fields still returned tag 10=`ff`, tag 11=`00`,
tag 12=`0000`; tags 13/14 were rejected with invalid-arguments. The tag-11 zero
despite the operator-confirmed loaded pack further establishes that this raw value
must not be presented as an actual remaining-sheet count. The Select capability
table still does not advertise these fields. Config tags 6/7 again returned zero
despite not being advertised; tag 8 was rejected. Identity tags 15–18 returned
not-found, status tags 15–18 invalid-arguments, and copy progress was rejected.
These are expected optional-field results, not core-probe failures.

Operational metric changes since the earlier research capture were USB attaches
14→15, precharge battery 87→99, sleeps 36→37, and auto power-offs 8→9. These are
interval changes, not evidence that this run caused them. All these counters were
unchanged between the two new sessions. Signal-strength key 22 varied 51→53 over
BLE while RFCOMM stayed 128; its units and sentinel interpretation remain unknown.

Both raw transmit traces were decoded and checked against the read-only allowlist,
including dynamically granted/revoked capability-file handles: **124 application
requests in the first session and 95 in the reconnect session**, 219 total.
No print, upload, settings-write, clock-write, setup-version write, resource
allocation, security-change, trigger, reset, or firmware request was sent.
The pairing-control GATT read was deliberately omitted because it is not ordinary
telemetry and previously stalled a session. Its omission is not a permission issue.

Private evidence (ignored, mode 0600):

- `logs/20261020T152833.518962Z-probe.jsonl` and
  `logs/live-newer-apk-validation.json`: full investigation, observation, beacon.
- `logs/20261020T153128.719530Z-probe.jsonl` and
  `logs/live-newer-apk-reconnect.json`: fresh reconnection and repeated reads.
- `logs/live-validation-audit.json` and `logs/live-reconnect-audit.json`: transmit
  audit and comparison results. The reconnect session contains no timed samples;
  the stability result above is from the first session's 12 actual samples.

These reads validate retrieval, consistency, stability, and reconnection on this
unit/firmware. The APK's setup-marker and First Print interpretations remain
source-backed meanings, not experimentally proven firmware transitions; testing
those transitions would require changing state. Physical printing, image geometry,
calibration behavior, actual error transitions, and exact sheet inventory remain
outside this validation. This follow-up changed documentation only, so the prior
software test results below were not rerun or represented as new results.

## Software checks completed

- Editable package install on macOS, Python 3.14.
- CLI entry point/help.
- IOBluetooth framework import, delegate initialization, and availability of the
  native RFCOMM channel-open selector.
- 293 automated cases, including 248 opcode-rejection cases and
  a regression case for the physical Select's fixed-width identity fields.
- Configuration decoding, rejected optional fields, raw RGB preservation,
  unsolicited-event routing, simulated extended probe, and native SDP serialization.
- Ruff lint and formatting checks.
- Live discovery failure recorded as a JSON result and private JSONL trace.

## Initial live attempt

CoreBluetooth reported authorization `0` (not determined). A scan did not return
within its initialization deadline. This establishes an authorization/initialization
block, not a device compatibility failure or evidence that the printer was absent.
No physical Select protocol response was received.

## Physical Select probe

Validated on macOS 27.0.1, Python 3.14, Bleak 3.0.2, PyObjC 12.2.2.
Printer firmware `G1L1FA2105AR`, hardware version `4138`, SuperModel `0x48D3`,
SubModel `3`, FeatureSetVersion `9`. Hardware identifiers are kept in the private
trace rather than this repository.

CoreBluetooth authorization was allowed (`3`) at the successful discovery. No
privacy permission toggle or TCC database modification was needed during this
validation. Classic pairing initially did not exist; a one-time pairing attempt
through Apple's IOBluetoothDevicePair API returned success, and macOS subsequently
reported the Select as paired. This pairing is specific to the printer.

Actual responses revealed DeviceId is a fixed 16-byte field and FeatureSetVersion
is uint16 LE, whereas the reference-inspired parser assumed strings. Corrected
both definitions and added a synthetic regression fixture without device secrets.

One BLE connection attempt immediately after pairing timed out before the session
opened. A subsequent full probe with `--scan-seconds 5 --timeout 20` succeeded:
both transports returned identical identity, 97% battery, and idle status. No
attributes were rejected. RFCOMM reported one host; the preceding BLE status read
reported zero. The transient timeout's cause has not been established.

Private successful trace: `logs/20261020T063119.294277Z-probe.jsonl`. The filename
uses UTC. It is excluded from Git. Its TX audit showed, on **each** transport:
one IF_CONFIG, one CONN_SETUP, ten RD_SYS_ATT, and one RD_STATUS request. All 26
requests passed the read-only allowlist. Both disconnect events were recorded.

## Hardware acceptance

- [x] BLE discovery identifies the Select and retains its raw service data.
- [x] Identity read confirms SuperModel `0x48D3`.
- [x] BLE reads return firmware, battery, printer state, and Bluetooth MAC.
- [x] MAC read maps to the intended paired Classic Bluetooth device.
- [x] RFCOMM channel 2 opens while BLE stays connected.
- [x] RFCOMM reads return matching Select identity, firmware, battery, and status.
- [x] Raw TX/RX frames and decoded results are retained for both transports.
- [x] Normal completion records disconnects for both owned connections.
- [x] No settings or print commands occur in the recorded transcript.
- [ ] Physical failure/interruption cleanup after both transports are open.

Do not mark hardware acceptance complete from simulated tests. Record exact
firmware, host/runtime versions, observations, and the private trace location when
the physical probe succeeds. Keep hardware identifiers and traces out of Git by
default.

## Extended read-only validation

Completed with `probe --extended --scan-seconds 20 --timeout 20`; successful
trace `logs/20261020T064831.310453Z-probe.jsonl`. Both transports returned the same
five configuration values and first-print timestamp. Firmware remained
`G1L1FA2105AR`; current status was idle with 99% battery. GATT inventory and fresh
SDP records were retained. The additional status reads returned three fields and
rejected three others (including copy progress). These optional rejections are
reported in JSON and do not mean the core probe failed.

The TX audit verified all 51 application requests were allowed reads or session
negotiation: eleven identity, five configuration, and two setup requests on each
transport; eight BLE and seven RFCOMM status requests. No print/settings writes
occurred. Both normal disconnect events were recorded.

An earlier extended probe stopped on an unsolicited `03 03 00` application
message. The transport now logs command `03` separately; a regression test verifies
it cannot satisfy the request/reply queue. Other ambiguous unexpected messages
still fail closed. The event's payload remains undecoded.

Short scans sometimes missed the printer; a subsequent 20-second scan succeeded.
The cause has not been established. This does not justify inferring shutdown or a
specific Bluetooth failure. Full findings and evidence grades are in [RESEARCH.md](RESEARCH.md).

## Capability/metrics follow-up

Physical `probe --investigate --listen-beacon` passed on both transports. Device
capability tables were identical, and metrics dataset 1 paginated to completion.
The printer page counter remained 10; the calibration counter remained 2.
Five seconds of passive channel-1 reception produced six identical beacon packets
with no application data writes to that channel. No print or configuration-write
opcode occurred in the 95-request combined successful trace.

New tests cover binary feature TLV parsing, scoped file handles and their release
on errors, metrics iterator following/cycle detection, variable-length strings,
source-backed status labels, and the channel-1 write prohibition. Optional direct
GATT pairing-control reads timed out and are disabled by default.
