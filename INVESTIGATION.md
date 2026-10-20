# Unattended, read-only Select investigation

Started 2026-10-20 06:56 UTC with an approximate 30-minute upper bound. The
operator confirmed the printer was connected to a micro-USB charger and would not
be available to change physical conditions. No print, configuration write, clock
write, reset, trigger action, firmware operation, or authentication change was sent.

## Main results

1. Downloaded the Select's own 227-byte binary capability table over BLE and
   RFCOMM. Results are byte-for-byte identical.
2. Read and paginated metrics dataset 1 on both transports, including the printer
   page counter and calibration/error counters.
3. Found stronger field definitions in a statically inspected 2022 HP app artifact.
4. Identified the extra GATT characteristic as pairing control. It timed out and
   was removed from default investigation behavior.
5. Confirmed the custom channel 1 beacon with receive-only access.
6. Corrected several earlier assumptions; these supersede the earlier notes.

## Source provenance and limits

Artifact: `app/HP600AndMaintenanceRealeaseBuildDate.19.05.2022.apk` in the public
[aditya0594/HP_Sprocket test repository](https://github.com/aditya0594/HP_Sprocket).
It was downloaded as data and never installed or executed. APK SHA-256:
`7df25e8c9fe724176640d20a3a037ae274eb1800306058af01b7507384852067`.

It contains `com.hp.impulselib.HPLPP` classes and a signing certificate whose
subject is HP / PTP / Impulse Sprocket. That subject alone does not authenticate it
against a production Google Play release. Treat it as a mirrored historical app
artifact, not an independently authenticated current vendor specification. Its
request formats and many typed values were then checked against physical Select
responses. The runtime itself was not used to control the printer.

Static inspection used JADX 1.5.6 from the official skylot/jadx release. The APK,
DEX, generated Java, certificate, and analysis tools remain under ignored `logs/`.
No proprietary app binaries or decompiled source are committed. Our Python
implementation was written independently from the wire definitions.

Useful artifact classes/resources:

- `HPLPP/messages/BaseMessage`: command IDs.
- `FeatureDiscoveryRequestMessage`, `FeatureDiscoveryResponseMessage`,
  `FileReadRequestMessage`, `FileReadResponseMessage`, `model/FeatureTable`:
  capability download and binary table schema.
- `ReadMetricsDatabaseRequest`, `ReadMetricsDatabaseResponse`,
  `util/MetricsDatabaseReader`, `res/raw/fw_counters.json`: metrics pagination,
  record widths, and key labels.
- `model/SystemFlags`, `BatteryStatus`, `QueueStatus`, `SystemAttributeFields`:
  status interpretations and attribute names.
- `BLEcommClient`: purpose of the pairing-control characteristic.
- `device/SprocketDeviceType`: Select image-input profile.

## Corrected commands and formats

| Command | Confirmed role / request |
| --- | --- |
| `2A` | Feature discovery, no arguments |
| `2B <handle> <format>` | Feature discovery response; format 2 = binary |
| `28 <handle> 01` | Read next chunk of the returned capability file |
| `29 <handle> <remaining:u32LE> <data>` | File-read reply |
| `3A 01 <iterator:u16LE>` | Read metrics database 1 |
| `3B 01 <next-iterator:u16LE> <records>` | Metrics reply, each record key:u16LE/value:u32LE |
| `2C` / `2D` | List jobs; Select returned an empty list |
| `03` | TARGET_EVT; the historical app ignores its payload |

The wiki's `RD_FEATURE` label for `3A` was incorrect for this firmware. Initial
short `3A` forms failed because dataset + iterator were missing. Request forms
with three argument bytes succeeded; surplus zero arguments were tolerated in
the initial bounded experiment, but the CLI now sends only the actual schema.

The successful dataset-1 first reply returned iterator `0x8000`; following that
exact iterator returned additional keys and iterator zero. Do not treat the high
bit as an automatic end-of-data flag. Capability file reads are separately scoped
to a handle just returned by discovery and bounded to 64 KiB / 64 chunks.

Binary feature tables are TLV: tag:u8, value-length:u16LE, value bytes. Array
values start with a base-128 variable-length element count. Identity strings also
use base-128 length integers; the earlier one-byte-only parser was incomplete.

Error 6 = invalid arguments; error 5 = not found; error 14 = malformed message in
the inspected library. The Select exhibited those errors on unsupported fields
and incomplete metrics requests. No unknown command-opcode sweep was performed.

## Device-advertised capabilities

Firmware `G1L1FA2105AR`, capability version 9, protocol version 1:

- Interfaces `[1,2]`: BLE and Bluetooth Classic.
- MIME types `[1]`: JPEG in the HP protocol's file-type convention.
- System attributes: tags 1 through 14.
- System configurations: tags 1 through 5.
- Status fields: `[1,2,3,5,6,7,9]`.
- Job properties: `[1,2,3,4]`: name, color label, number of copies, submission time.
- Printer-name limit 32; job-name limit 16. Character/byte limits were not tested.
- Firmware LED colors: `#ffffff`, `#002ee0`, `#3f006f`, `#ff348b`, `#967d00`, `#008400`.
- Separate UI palette: `#dafffe`, `#0076eb`, `#9e4cf7`, `#ff64fb`, `#fbff66`, `#0ee679`.
- Security modes `[1,2,3,4]`, authentication modes `[1]`, key schemas `[1]`.
  Their detailed semantics remain unknown; no security settings were changed.
- Metrics databases `[1]`; partial-reset flag zero; auxiliary-URL maximum zero.
- Trigger-action IDs `[2]`. The historical app calls action 2 reboot. It was not
  invoked, and firmware-version correspondence of the action enum was not tested.
- Update types `[0,1]`; timings `[0,1]`. The inspected app names type 1 background
  and timings 0 now / 1 shutdown. No firmware update was attempted.
- Target-event identifiers `[1,2,3,5,6,8]`; payload semantics remain unknown.
- Multi-key list empty; resource identifiers `[1]`.

Raw advertised request IDs, decimal:
`4,6,8,10,12,14,16,18,20,22,24,26,28,32,34,36,38,40,42,44,46,48,50,52,54,56,58`.
Advertising a command is not permission for our CLI to send it. Printing, writes,
updates, authentication operations, resource allocation, and triggers stay denied.

Status field 4 (progress), fields 10–12 (supply-related leads), and config tags 6–7
returned zeros or placeholder values despite being absent from these lists.
Successful replies alone do not establish supported semantics. No remaining-paper
count can be inferred. Attributes 15–18 returned not-found; status tags 15–18 and
config tag 8 returned invalid-arguments. This agrees with the advertised boundaries.

## Status and identity meanings

System bits named by the inspected HP library:

| Bit | Mask | Name |
| --- | --- | --- |
| 0 | `01` | Time invalid |
| 1 | `02` | Battery critical |
| 2 | `04` | Print busy |
| 3 | `08` | Out of paper |
| 4 | `10` | Low on supplies |

Our observed system value 1 decodes to time-invalid. We deliberately did not set
the clock to clear it. Remaining bits are unknown; the earlier AI-generated gist's
bit-5 low-battery label is not present in this app implementation.

Battery status is an enum: 1 in use, 2 charging, 3 overheat, 4 error. Queue status
is an enum: 1 empty, 2 full, 3 paused, 4 populated. The gist's extra queue state 5
is not defined here. The CLI preserves raw values and maps unknown codes to unknown.

During 12 paired status samples over two minutes with USB power confirmed by the
operator, battery percentage remained 100 and status stayed 2. This agrees with
the app's charging label, but no unplugged comparison was possible. “Charging” may
remain the firmware's state label while plugged in at full charge.

Newly named identity reads: tag 2 protocol version = 1; tag 7 security mode = 1;
tag 13 setup = 0. The meaning of security-mode and setup values remains unresolved.
Connection security-level byte `0x21` remains undecoded.

Tag 14 is **BornOnDate**, raw Unix timestamp `1775953184`. It is April 11, 2026 at
5:19:44 PM Pacific, but does not independently establish the date of first printing.
The JSON key was corrected from `first_print_timestamp` to `born_on_timestamp`.

## Metrics read from the printer

Labels come from the artifact's `fw_counters.json`; values come from physical
dataset-1 replies, not app-local estimates. Counters may be resettable or defined
differently by firmware, so do not call them guaranteed lifetime totals.

| Metric | Value |
| --- | ---: |
| Printer pages | 10 |
| Paper jams | 0 |
| Calibration-card cycles | 2 |
| Out-of-paper events | 0 |
| Incorrect-paper-type events | 0 |
| Long power presses | 17 |
| Manual sleep events | 4 |
| USB attach events | 14 |
| Battery level before charge | 87 |
| Top-cover opens | 15 |
| Pages since last cover opening | 0 |
| Pages since last calibration | 0 |
| Power-on count | 16 |
| Reset presses | 2 |
| Sleep events | 36 |
| Automatic power-offs | 8 |
| Concurrent devices | 1 |

Key 22 is named signal_strength and returned 53 over BLE versus 128 over RFCOMM
in one matched read. Units/sign/sentinel meaning are unknown. Do not interpret 128
as dBm or a percentage. The sleep-event counter changed during the broader session;
connection/observation activity can affect operational counters without settings
writes. The printer-page counter remained 10 and calibration counter remained 2.

## Image-input profile: stronger evidence, still no physical print

The historical HP library's Select/GrandBahama profile uses 768 × 1152 with JPEG
quality 90. This independently corroborates openZinkBooth's input profile. It is
still an app-selected raster, not a device-reported native head resolution or proof
that other JPEG dimensions are rejected. No image was transferred in this work.

## Custom channel and pairing characteristic

Channel 1 was opened alongside the existing connections for five seconds. It sent
six copies of `FF 55 02 00 EE 10`. The listener transmitted zero application bytes;
its exchange method rejects all writes. Beacon fields remain undecoded.

The historical HP library names `...3dd5acdd2eee` pairing control and reads it from
its pair procedure. Our direct read timed out; a following BLE request also stalled
in that session. Disconnecting and a new session restored normal operations. This
is evidence of a timeout/stall, not a proven root cause. It is opt-in and executed
last, never part of ordinary capability/configuration reads.

## Evidence and scope

Successful combined trace: `logs/20261020T071146.489201Z-probe.jsonl`.
95 application requests audited against the current allowlist, including scoped
capability-file reads. Configurations and capability tables matched across both
transports. Channel 1 transmitted zero bytes. No cleanup error recorded.

Other useful traces: `logs/20261020T070909.908718Z-probe.jsonl` (first successful
capability/metrics download); the private `investigate-console.json` result and its
referenced trace contain the two-minute status series. Earlier malformed requests
are retained locally as evidence, but were removed from the normal CLI sequence.

Remaining open: security-level encoding, setup/security-mode values, target-event
payloads and beacon bytes, exact supply/paper semantics, physical output geometry,
color calibration, recovery and physical-job completion. These were not guessed
or tested by triggering a print, fault, reset, or update.

Software validation: 293 automated tests passed, including a 227-byte physical
Select capability fixture with no device identifiers, scoped read-handle tests,
metrics pagination/cycle detection, enum/flag decoding, variable-length strings,
and the passive-channel write prohibition. Ruff and dependency checks passed.
