# zink-probe

Milestone 1: **read-only macOS Python diagnostics** for the **HP Sprocket Select**
over BLE and Bluetooth Classic RFCOMM, plus an explicit, bounded settings test.
Ordinary `discover` and `probe` sessions remain read-only. A separate, hash-pinned
[CAL-02 first-sheet experiment](experiments/calibration/REVISION_2.md) implements
one explicitly authorized print attempt; this is not yet a general print driver.

This is a separate project because the reference HP implementation is an Android
photo-booth app, while the eventual goal here is a reusable desktop printer backend
and later PAPPL integration. Xiaomi and Canon use different protocols. Their drivers
are references, not dependencies. The parent `zink` directory holds those independent
repositories; this repository owns only `zink-probe`.

## Install

Use Python 3.11 or newer on macOS. Development was checked with Homebrew Python
3.14, Bleak 3.0.2, and PyObjC 12.2.2.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/zink-probe --help
```

The Python used for `venv` must be 3.11+. The older Apple-provided Python 3.9 is
insufficient. For the initial development machine, `/opt/homebrew/bin/python3.14`
was used explicitly.

## Discover and probe

1. Power on the Select nearby. Disconnect the vendor app if it holds the printer.
2. Allow Bluetooth access for the launching application/Python when macOS asks.
   Check **System Settings → Privacy & Security → Bluetooth** if necessary.
3. Discover BLE candidates:

   ```sh
   .venv/bin/zink-probe discover --scan-seconds 10
   ```

4. Pair the Select for Classic Bluetooth in **System Settings → Bluetooth**.
   The CLI does not change pairing records or unpair devices.
5. Probe the single Select advertising model `0x48D3`:

   ```sh
   .venv/bin/zink-probe probe
   ```

   If there are multiple candidates or the model advertisement is absent, select
   the exact BLE UUID shown by discovery:

   ```sh
   .venv/bin/zink-probe probe --ble-id YOUR-MACOS-BLE-UUID --timeout 10
   ```

`--ble-id` selects a discovered candidate; it does not bypass the identity check.
The device must report Select SuperModel `0x48D3` through protocol identity reads.
The CLI refuses ambiguous automatic selection and refuses other HP models.

macOS BLE identifiers are UUIDs, not MAC addresses. After BLE setup the probe reads
the device's Bluetooth MAC attribute, reverses its wire byte order, and opens
**RFCOMM channel 2** at that address while keeping BLE connected. It does not use
Bleak's undocumented MAC-address lookup option or guess the target from its name.

### Extended read-only snapshot

```sh
.venv/bin/zink-probe probe --extended --scan-seconds 20 --timeout 20
```

Adds individually queried configuration fields, born-on timestamp, GATT service
metadata, a fresh Classic SDP query, copy-progress and five cross-device status-tag
investigations. It also rereads BLE status with RFCOMM open to compare host count.
Short scans have occasionally missed this Select; 20 seconds succeeded in the
extended validation. No settings are changed.

Unsupported optional reads are recorded as rejected/omitted with raw replies;
they do not make the otherwise complete core probe fail. Exit `0` means the core
identity/status checks succeeded, not that every experimental field is supported.
The GATT inventory lists properties and descriptors; it does not read unknown
characteristics. SDP returns typed service attributes, UUID bytes, and channels.
Raw application frames are logged, but native GATT/SDP discovery packets are not
an HCI capture; their decoded metadata is retained in the result instead.

Status bit observations show hex, binary, and set-bit positions. Battery and queue
status are enums; labels and system flag bits 0–4 now follow the inspected HP app
artifact. Raw values and unknown system bits are preserved.
See [RESEARCH.md](RESEARCH.md) for confirmed values and tentative interpretations.

### Capability table, metrics, and bounded investigation

```sh
.venv/bin/zink-probe probe --investigate --listen-beacon --scan-seconds 20 --timeout 15
```

`--investigate` implies `--extended`. It downloads the device's capability table
(`2A`, then scoped `28 <handle> 01` file reads), reads metrics dataset 1 (`3A`),
and performs a fixed list of additional identity/config/status reads. Capability
file handles are permitted only after discovery returns them, and permission is
removed after the download. Downloads and iterator pagination have hard bounds.
The capability file is read from the printer; no image/file upload is implemented.

`--listen-beacon` opens custom RFCOMM channel 1 for five seconds, receives bytes,
and closes it. Channel 1 rejects every application write in code. This confirmed
the `FF 55 02 00 EE 10` beacon on Select. Normal protocol requests use channel 2.

Optional status observation: `--observe-seconds 120` samples both transports every
ten seconds and reads back configuration afterward. Maximum is 300 seconds.

`--read-diagnostic-gatt` separately attempts the `...2eee` read at the very end.
The inspected app identifies it as **pairing control**, not ordinary telemetry.
It timed out on this Mac and a subsequent BLE request also stalled in that session;
it is **off by default**, including in investigation mode. Do not use it for a
normal configuration/capability snapshot.

Corrections to earlier research: `3A` is read-metrics-database, not read-feature;
feature discovery is `2A`. Identity tag `0E` is now reported as `born_on_timestamp`
rather than `first_print_timestamp`, following the HP library's BornOnDate name.
It is not proof of the date of the first physical print. Strings use bounded
variable-length integer lengths, not an unconditional one-byte length.

### Temporary settings test (changes settings, then restores)

```sh
.venv/bin/zink-probe settings-test --scan-seconds 20 --timeout 15
```

Use this only when temporary printer-setting changes are intended. It checks the
Select identity on both transports, requires matching configuration, an idle
printer and empty remote queue, and verifies the required advertised capabilities
and standard color palette. It records the baseline, changes sleep to a different
app-defined choice, verifies it over both connections, and restores the original
value through the other connection. It then does the same for a standard LED color.
On the tested unit this was sleep 3→5→3 minutes and white→blue→white.

Only the exact temporary/restoration bytes are authorized during each transaction.
The transport policy additionally rejects other configuration tags, nonstandard
RGB encodings, multi-setting writes, print/upload/update commands, and pause/resume.
There is no arbitrary write argument. Grants are revoked after each transaction.
The test attempts restoration even when a write acknowledgement is lost or the
task is cancelled; it stops on error and records whether restoration was verified.
Repeated interruption, process termination, or a lost physical connection can
prevent restoration, so inspect the result rather than assuming it succeeded.
The full final configuration and page/calibration counters must match the baseline
for success. Auto-off is never changed by this command.

Physical settings validation and the subsequent fresh-connection check are in
[SETTINGS_RESEARCH.md](SETTINGS_RESEARCH.md). Raw traces remain local and private.

## Output and logs

Both commands print JSON to stdout. A successful probe includes `ble` and `rfcomm`
sections with identity, firmware, battery percentage, numeric/status-name fields,
session negotiation results, and any rejected optional identity attributes.

Exit codes:

- `0`: discovery completed (possibly with no candidates), or both probe transports
  returned the required identity, firmware, battery, and status fields.
- `1`: probe/transport/protocol failure, including no matching printer; partial
  results are retained in stdout and the trace.
- `2`: CLI arguments, unsupported host, or trace creation error.
- `130`: interrupted by the operator.

JSONL traces default to `logs/<UTC-timestamp>-<command>.jsonl`. Use `--log PATH`
after the subcommand to choose a **new** file. Existing files are never overwritten.
Each record has UTC and monotonic timestamps. Frames include transport, direction,
layer, byte length, and raw hex. BLE notifications and writes are logged; RFCOMM
stream chunks and reconstructed messages are logged separately. RX stream chunks
retain the original HP+ envelope bytes even when reads split or combine frames.
Results and failures are also logged and flushed immediately.

Logs can contain device names, serial numbers, Bluetooth addresses, and nearby HP
advertisement data. They are created with mode `0600` and ignored by Git. Review
them before sharing. No cloud service is used by the CLI.

## Read-only boundary

For ordinary discovery/probe sessions the transport code validates every outbound
command against a read-only allowlist:

| Command | Purpose |
| --- | --- |
| `0A 01 00` / `0A 02` | Negotiate BLE / RFCOMM interface |
| `24 00 10` | Announce host receive capacity of 4096 bytes |
| `04 <known identity tags>` | Read identity, firmware, hardware version, and optionally born-on timestamp |
| `08 <known status tags>` | Read battery, state, progress, job/queue status, hosts |
| `08 <single tag 0A–0E>` | Extended cross-device status research; preserve raw replies |
| `1A <single tag 01–05>` | Read sleep, auto-off, LED RGB, pause, and host threshold |
| `2A` | Discover read-only feature-table file |
| `28 <granted handle> 01` | Read the capability file; no general file access |
| `3A 01 <iterator:2LE>` | Read metrics dataset 1 |
| `2C` and fixed additional read tags | Investigation-only empty-job-list and field research |

BLE additionally sends protocol ACK `00` for multi-frame responses when requested
by the negotiated ACK period. These writes establish session state and acknowledge
reads; “read-only” does not mean passive Bluetooth sniffing. The separate
`settings-test` command temporarily adds exact `1C 01 <minutes:u16LE>` and
`1C 03 <standard RGB>` grants, with restoration as described above. Time writes,
resource allocation, print-start, uploads, pause/resume, reboot, and firmware
operations remain unavailable. There is no arbitrary-command escape hatch or image
dependency. The settings-test trace explicitly records `read_only: false`.

A rejected connection-setup command is logged and the probe attempts actual reads,
following a quirk observed in the Sprocket 200 reference. Successful reads, rather
than an assumed successful handshake, determine the outcome. Other protocol errors
stop the probe; transport timeouts are not automatically retried.
Unsolicited command `03` (TARGET_EVT in the inspected library) messages are logged
separately and cannot satisfy a response queue. Payload meanings remain undecoded.

## Validation and limits

```sh
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Tests cover command rejection, typed identity/status decoding, MAC byte order,
fragmented/coalesced RFCOMM frames, BLE sequencing and ACK decisions, malformed
responses, negotiation rejection, a simulated two-transport probe, wrong-model
rejection, private logs, partial results, and cleanup after RFCOMM failure.
Synthetic transcript tests establish software behavior, not Select compatibility.

**Physical Select validation passed** for discovery and identity/status reads over
both BLE and RFCOMM channel 2 on macOS 27.0.1, firmware `G1L1FA2105AR`. Both
transports returned matching identity, 97% battery, and idle status. Native pairing
was completed for this printer before the successful probe. The raw TX trace was
audited against the read-only allowlist. See [VALIDATION.md](VALIDATION.md) for
remaining limits, including a transient connection timeout after pairing.

Known limits:

- Validation covers one Select and firmware version; other units/firmware and
  printing behavior are unverified. The physical probe corrected two reference
  assumptions: DeviceId is a fixed 16-byte value (reported in wire-order hex), and
    FeatureSetVersion is a little-endian uint16.
- Classic pairing must already exist. RFCOMM channel 2 was confirmed on this Select.
- BLE scan initialization has a deadline of scan duration + 15 seconds. macOS
  permission UI may require operator action. Native synchronous RFCOMM open/write
  calls have OS-controlled blocking; `--timeout` bounds response waits, not those
  native calls. There is no claim of a global hard timeout.
- No automatic reconnection, continuous polling, printing, or PAPPL integration.
- Optional unsupported identity tags are reported individually. Unknown fields,
  invalid framing, and truncated data fail explicitly rather than guessing.

## Protocol provenance

This Python implementation was written independently against the documented wire
format, without copying the reference projects' source code.

- [openZinkBooth protocol wiki](https://github.com/oliexdev/openZinkBooth/wiki/Sprocket-200-Bluetooth-Protocol)
  (local wiki snapshot `c864f81`).
- [openZinkBooth](https://github.com/oliexdev/openZinkBooth)
  (local source snapshot `8e1df0b`): model ID and typed field definitions.
- [Bleak API](https://bleak.readthedocs.io/en/latest/api/index.html): macOS discovery
  and GATT transport.
- [Apple IOBluetooth RFCOMM API](https://developer.apple.com/documentation/iobluetooth/iobluetoothdevice/openrfcommchannelsync(_:withchannelid:delegate:)):
  native Classic Bluetooth transport through PyObjC.

See [VALIDATION.md](VALIDATION.md) for the Milestone 1 acceptance checklist.
See [INVESTIGATION.md](INVESTIGATION.md) for the time-bounded follow-up, source
provenance, firmware counters, and the complete capability-table findings.
See [IOS_EXPLORATION.md](IOS_EXPLORATION.md) for the acquired official iOS package,
readable declarations/resources, and the limits imposed by encrypted code.

See [NAMING_AND_DEVICE_FAMILIES.md](NAMING_AND_DEVICE_FAMILIES.md) for confirmed,
probable, and unknown acronym meanings, resolved app profiles, and future device
support candidates. These notes do not expand the probe’s supported-model list.

See [ANDROID_RUNTIME.md](ANDROID_RUNTIME.md) for the isolated original-APK render
experiment, measured JPEG output, and PhotoFix pointer-tagging findings.

See [EDITOR_PIPELINE.md](EDITOR_PIPELINE.md) for offline measurements of upstream
rotation, fit/fill, crop, white borders, and intermediate image encoding.

See [PYTHON_IMAGE_PREPARATION.md](PYTHON_IMAGE_PREPARATION.md) for the independent
offline Python raster/JPEG preparation experiment, Android comparisons, and
remaining PhotoFix/editor differences. It writes local images only.

See the [offline calibration package](experiments/calibration/README.md) for the
reviewable SELECT-CAL-01 sheet, exact Python/Android comparisons, and a future
single-sheet measurement plan. [PRINT_TRANSACTION.md](PRINT_TRANSACTION.md)
traces submission, transfer acknowledgements, queue activation, completion, and
failure handling without sending print commands.

The revised [SELECT-CAL-02 chart and images](experiments/calibration/REVISION_2.md)
add crop-depth gauges, repeated controls, slanted edges, and tonal/detail tests.
A separate hash-pinned first-sheet experiment has explicit one-print authorization;
ordinary diagnostic sessions retain their default read-only policy.

The [first authorized physical print](experiments/calibration/FIRST_PRINT.md)
accepted the pinned CAL-02 JPEG and reported one completed page. It also exposed
unreliable progress percentages and candidate job/status event payloads.
Subsequent [photographs of the printed chart](experiments/calibration/PHOTO_ANALYSIS.md)
confirm physical output, suggest about 4% edge loss in each input dimension, and
show a strong directional fine-detail difference. These preliminary observations
do not yet establish native resolution or justify a fixed printer correction.
[Closer photographs and brightness profiles](experiments/calibration/CLOSEUP_ANALYSIS.md)
show that faint one-pixel vertical periodic detail survives, refining the initial
wide-photo impression of a solid dark patch. Its captured contrast remains much
lower than the horizontal counterpart.
Approximate [operator measurements](experiments/calibration/SCALE_PEN_ANALYSIS.md#subsequent-operator-measurements)
of a 53×83 mm reference frame on 58×87 mm paper imply about 322–323 input
pixels/inch in both directions and corroborate roughly 4% total edge loss per
dimension. This establishes image placement approximately, not native heater DPI.
