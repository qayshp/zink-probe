# zink-probe

Milestone 1: a **read-only macOS Python CLI** for investigating the **HP Sprocket
Select** over BLE and Bluetooth Classic RFCOMM. No printing is implemented.

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

Adds individually queried configuration fields, first-print timestamp, GATT service
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

Status bit observations show hex, binary, and set-bit positions. Battery/queue
fields may be enums rather than bitmasks. No speculative bit names are assigned.
See [RESEARCH.md](RESEARCH.md) for confirmed values and tentative interpretations.

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

The transport code validates every outbound command against an allowlist:

| Command | Purpose |
| --- | --- |
| `0A 01 00` / `0A 02` | Negotiate BLE / RFCOMM interface |
| `24 00 10` | Announce host receive capacity of 4096 bytes |
| `04 <known identity tags>` | Read identity, firmware, hardware version, and optionally first-print timestamp |
| `08 <known status tags>` | Read battery, state, progress, job/queue status, hosts |
| `08 <single tag 0A–0E>` | Extended cross-device status research; preserve raw replies |
| `1A <single tag 01–05>` | Read sleep, auto-off, LED RGB, pause, and host threshold |

BLE additionally sends protocol ACK `00` for multi-frame responses when requested
by the negotiated ACK period. These writes establish session state and acknowledge
reads; “read-only” does not mean passive Bluetooth sniffing. No settings-write, time,
resource allocation, print-start, file-transfer, reboot, or firmware commands exist
in the CLI. There is no arbitrary-command escape hatch and no image dependency.

A rejected connection-setup command is logged and the probe attempts actual reads,
following a quirk observed in the Sprocket 200 reference. Successful reads, rather
than an assumed successful handshake, determine the outcome. Other protocol errors
stop the probe; transport timeouts are not automatically retried.
Unsolicited command `03` messages observed on Select are logged separately and
cannot satisfy a request's response queue. Their meaning is not yet decoded.

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
