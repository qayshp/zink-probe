# Select read-only configuration and protocol findings

Scope: one physical HP Sprocket Select, firmware `G1L1FA2105AR`, on macOS 27.0.1.
These observations do not establish behavior on other firmware or HP models.
No print, settings-write, clock-sync, resource-allocation, or job-creation command
was sent. No settings or physical conditions were deliberately changed in this run.

## Confirmed configuration reads

Both BLE and RFCOMM returned identical results from command `1A`:

| Tag | Raw response | Decoded value |
| --- | --- | --- |
| `01` | `1B 01 03 00` | Sleep timer: 3 minutes |
| `02` | `1B 02 3C 00` | Auto-off: 60 minutes |
| `03` | `1B 03 FF FF FF` | LED RGB: `[255,255,255]`, white |
| `04` | `1B 04 00` | Pause-printing value: 0, not paused |
| `05` | `1B 05 03` | Host threshold: 3 |

Field names/units follow the openZinkBooth protocol reference. Successful decoding
does not independently test the timers' real elapsed behavior. Host threshold 3
is consistent with a connection limit but was not validated with three clients.
No nearest-color mapping or timer preset rounding is performed.

First-print attribute `0E` returned uint32 LE `1775953184` on both transports.
Interpreted as Unix seconds: `2026-04-12T00:19:44Z`, or April 11, 2026 at
5:19:44 PM America/Los_Angeles. This is the device-reported value interpreted using
the reference format; historical clock accuracy and what counts as a first print
are not independently verified.

## Additional status reads

The following queries are individual `08 <tag>` reads. The names are leads from
a different HPLPP device; the complete replies are preserved without guessing
unknown field widths.

| Tag | Candidate name | Select reply, both transports | Conclusion |
| --- | --- | --- | --- |
| `08` | Copy progress | `01 08 06` | Rejected in this idle state |
| `0A` | Supply type | `09 0A FF` | Field exists, value `FF`; meaning unverified |
| `0B` | Supply level | `09 0B 00` | Field exists, value `00`; not a paper-count measurement |
| `0C` | Supply version | `09 0C 00 00` | Field exists, two zero bytes |
| `0D` | Supply selectability | `01 08 06` | Rejected in this idle state |
| `0E` | Cap status | `01 08 06` | Rejected in this idle state |

Error code `06` is called invalid arguments in the cross-device source, but that
label has not been verified from a Select specification. An idle rejection does
not establish that the field is unsupported in every state.

The supply fields may be generic protocol placeholders for printers with ink
cartridges. No conclusion about loaded ZINK sheets follows from their zero values.

## Flags, enums, and observed changes

| Field | Observation | What remains unknown |
| --- | --- | --- |
| System flags | `0x00000001`, bit 0 set | Actual Select flag definitions |
| Battery status | `0x02` | Likely enum; no cable-state experiment performed |
| Queue status | `0x01` | Likely enum; queue was idle and job ID zero |
| Session security | `0x21`, bits 0 and 5 set numerically | Whether flags or encoded levels; no security claim follows |
| Number of hosts | BLE reported 0 before RFCOMM, then 1 with RFCOMM open; RFCOMM also reported 1 | It does not count our BLE and Classic links as two independent hosts |

A [PrintMaker HPLPP gist](https://gist.github.com/acoster/af1d78378bc16fbcd2f004e6b159f82c)
provides these **unverified candidate definitions**:

- System bits 0–5: time invalid, battery critical, print busy, out of paper,
  low supplies, low battery.
- Battery enum 1–4: discharging, charging, heat protection, battery error.
- Queue enum 1–5: empty, full, paused, populated, error.

This gist explicitly describes itself as generated with Antigravity, concerns a
different device, and does not supply sufficient provenance for those mappings.
It is a lead, not a Select specification. The current values are compatible with
some of these labels but do not prove them. In particular, system bit 0 as “time
invalid” is plausible because our probe never synchronizes the clock; we did not
write the clock to test that hypothesis. The CLI intentionally retains raw values
and unlabeled bit positions rather than promoting these guesses to facts.

Unsolicited application message `03 03 00` was observed on both transports during
the extended reads. Command `03` is routed separately from request replies. It
may be an event/notification, but the two payload bytes are not decoded and no
bit meanings are asserted.

## Bluetooth inventory

BLE exposes one discovered service: `6822d239-7b61-4718-bdc1-189221946209`.

| Characteristic suffix | Properties |
| --- | --- |
| `de55b3f9051e` | Write, write without response |
| `772fa9983658` | Read, notify, indicate; CCCD descriptor `2902` |
| `3dd5acdd2eee` | Read only; payload not read in this milestone |

The macOS stack reported a maximum write-without-response size of 512 bytes.
This is a host transport limit, not evidence that the printer reliably accepts
that size or that transfers would be fast. No standard Battery or Device
Information GATT service appeared in this inventory.

Fresh SDP returned two records, with no service-name attributes returned:

- Channel 1: custom UUID `00000000-DECA-FADE-DECA-DEAFDECACAFF`.
- Channel 2: Serial Port Profile UUID `0x1101` (profile version `0x0102`).

Channel 1 was discovered but not opened or probed. Channel 2 carried the read-only
HP+ requests. Full typed SDP attributes are kept in the private trace result.

## Still open

- Meaning of the Select system flags, battery/queue enums, session security field,
  and unsolicited command `03`.
- Read-only payload at characteristic `...2eee`.
- `RD_FEATURE` request schema and response layout. It was not sent: a command name
  alone is insufficient evidence for an arbitrary feature-ID sweep.
- Lifetime print count, real remaining-sheet count, temperature, battery health,
  and supported image formats/dimensions have not been obtained from this snapshot.
- Charging-state correlation could test battery enum 2 by comparing reads before
  and after an operator unplugs/replugs USB. That experiment has not been performed.

## Evidence and sources

- Private successful trace: `logs/20261020T064831.310453Z-probe.jsonl` (UTC filename).
  51 application requests audited against the read-only allowlist: 26 BLE, 25
  RFCOMM. Both disconnect events recorded; no cleanup error recorded.
- [openZinkBooth protocol wiki](https://github.com/oliexdev/openZinkBooth/wiki/Sprocket-200-Bluetooth-Protocol):
  configuration tags, first-print field, and known status field definitions.
- [Apple SDP query API](https://developer.apple.com/documentation/iobluetooth/iobluetoothdevice/performsdpquery(_:)):
  fresh asynchronous service discovery.
- PrintMaker gist above: cross-device leads only; no source code copied.
