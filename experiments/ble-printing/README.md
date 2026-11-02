# Select BLE printing feasibility — 2026-11-01 Pacific

**BLE is an intentional printing transport in the inspected Android library,
and the recovered FS firmware connects it to the same printer handlers as
Classic SPP and iAP. Physical printing over BLE is still untested.** This corrects
any earlier assumption that the Select's BLE interface is necessarily limited to
discovery and diagnostics.

The physical FA Select answered a bounded BLE-only inspection, including status,
metrics and the capability table. No print start, job/resource allocation,
image upload, clock update, persistent setting, pairing-control read or fast-BLE
request was sent. The existing portable engine and iOS printing transport are
unchanged. This is a feasibility investigation, not a new printing adapter.

## Evidence and confidence

| Question | Result | Evidence boundary |
|---|---|---|
| Does Android contain a BLE printing route? | Yes: explicit force-stay-on-BLE option and a reverse-connect fallback select BLE as the main controller used for print start and image writes. | Static decompilation; not an observed official-app BLE print. |
| Is it enabled by default? | The force-stay-on-BLE feature defaults to false; the normal path switches toward Classic. | Current inspected APK, not every version/model/runtime condition. |
| Can the recovered firmware dispatch print commands received over BLE? | Its BLE framing reaches the shared dispatcher and print-start/file-write handlers. | Hash-pinned FS firmware; not a dump of this FA printer. |
| Is there an explicit transport security check? | Yes, a shared per-command required-level comparison. Print start and file write require `0x11` in FS. | Static branch trace; level values are not MFi approval states. |
| Does this FA printer expose a usable BLE protocol session? | Yes; message limit 1000, reported security level `0x21`, identity, status, metrics and capability reads succeeded. | One existing Mac/printer pairing environment; no fresh pairing or iPhone CoreBluetooth test. |
| Will a BLE print complete? | Not established. | No job created and no image uploaded. |
| What is BLE throughput/recovery behavior? | Unknown. | Short read-only transactions do not measure sustained image transfer or interruption recovery. |

## Android path, with resolved transport selection

Artifact: official-package APK `3.0.2921.1`, version code `74251`, SHA-256
`6395bd47fa7c669dd5fbc4a5408a4d54dd8c1841e8581be898f3bf90caaa405c`.
See [APK provenance](../../NEWER_APK.md). Line numbers below refer to the local
JADX output for that artifact; vendor code/binaries are not redistributed.

Paths are relative to the decompiled `sources/` directory:

| Location | Finding |
|---|---|
| `com/hp/impulselib/device/GrandBahamaDevice.java:26`, `HPLPPZinkDevice.java:20`, `HPLPPDevice.java:39` | The Select-family device inherits the HPLPP device/client implementation. |
| `com/hp/impulselib/bt/HPLPPClient.java:134` | Constructs the common `MessageClient`. |
| `com/hp/impulse/sprocket/controller/FeaturesController.java:158,751,874` | Defines `HPLPP_STAY_ON_BLE`, default **false**, reads it and applies it to the library override. |
| `com/hp/impulselib/HPLPP/MessageClient.java:1216` | `sendBTCListen()` checks the override and chooses `setupStayOnBLE()` rather than the normal Classic-listen switch. |
| Same file, `:1388` | Reverse-connect setup falls back to staying on BLE when the reconnect controller or host MAC is unavailable. This is not a universal fallback for every Classic failure. |
| Same file, `:1406` | BLE pairing first, then interface-control request for fast BLE. A rejected fast-mode request still proceeds with BLE consolidation. Pairing failure stops it. |
| Same file, `:752` | `consolidateStayOnBle()` makes `bleController` the **main controller**. |
| Same file, `:915–956` | `noErrorSendPrint()` queues `PrintStartRequest` through **mainController**, then job properties/image transfer. |
| Same file, `:1342–1348` | `sendWriteMessage()` takes the image bytes and print-start file handle; chunk size is target maximum message size minus file-write header size. It queues `FileWriteRequest` through **mainController**. |
| Same file, `:809–848` | File-write responses advance transfer state and queue subsequent chunks through the same controller. |
| `com/hp/impulselib/HPLPP/Controller.java:217–226,343` | Mode BLE constructs `BLETransportInterface`; queued messages reach its `sendMessage()`. |
| `com/hp/impulselib/HPLPP/BLETransportInterface.java:280` | Serializes arbitrary protocol messages into BLE fragments. No print-opcode exclusion in this transport method. |
| `com/hp/impulselib/HPLPP/BLEcommClient.java:743` | Writes those fragments to the GATT TX characteristic. |

The BLE envelope differs from the HP+ Classic/iAP stream envelope. BLE uses a
one-byte sequence counter starting at 1, with the high bit set on the final
fragment; `0x00` is an acknowledgement packet. The Android transport starts with
a 20-byte packet budget and learns its protocol MTU through IF_CONFIG. Each
fragment reserves one byte for the sequence envelope. A native implementation
must also respect the platform's actual permitted GATT write size; the protocol
MTU is not evidence of the effective radio/ATT payload size.

The library's BLE pairing route reads a dedicated pairing characteristic, and
its fast-mode route sends InterfaceControl. **Neither was exercised here.**
Generic device support and a reachable code path do not prove all Select models
or firmware versions work through that route.

## Firmware path

Input is the previously recovered `G1L1FS2105AR_1.0.7` inflated main image:

- Main SHA-256: `4cc83261d16ab8078db3a38ae694017c26e6c681e1eca1e9bb41a437704c24ce`.
- Embedded Bluetooth HCD: 452 records starting at file offset `0x12583a`,
  ending at `0x1418de`.
- Reconstructed 4 MiB address-image SHA-256:
  `6c637fd1c7b404df4dd37651b77008592f277c6f6bccce2aa982fd1c2113bf6a`.
- The physical printer is **G1L1FA2105AR**, not this FS artifact. Retain that
  distinction even where its live responses agree.

All addresses below are **reconstructed Bluetooth runtime addresses**, not main
file offsets. Names describe our interpretation; these are not vendor symbols.
Thumb function pointers have their low bit set; executable addresses below do not.

| Transport configuration | Address | Framing table | Message callbacks | Printer handlers |
|---|---:|---:|---:|---:|
| BLE | `0x224308` | `0x221134` | `0x221150` | `0x2245e4` |
| Classic SPP | `0x224354` | `0x221118` | `0x221150` | `0x2245e4` |
| iAP | `0x224384` | `0x221118` | `0x221150` | `0x2245e4` |

The resolved receive chain is:

```text
BLE connection initializer 0x217cb8 -> configuration 0x224308
GATT write handler 0x217d8c -> helper 0x217d60
  -> receive dispatch 0x21de98
  -> BLE fragment receiver 0x21cd9c (configuration +4, vtable +12)
  -> complete-message callback 0x21de4e (configuration +0, callbacks +8)
  -> common command dispatcher 0x21cfe4
       opcode 12 / PrintStart -> case 0x21d2ce -> handler 0x21a874
       opcode 14 / FileWrite  -> case 0x21d304
                                data handler 0x21bdc8
                                empty-write handler 0x21bd84
```

The dispatcher uses configuration `+12` to find the printer handlers: `+0x14`
for print start, `+0x1c` for nonempty file writes and `+0x18` for empty writes.
Thus these are the **same handler pointers**, not merely similarly named
transport-specific routines. The inspected print-start/data handlers perform
job/handle/busy validation and forward the request; no direct BLE exclusion was
found in these inspected paths. This is not proof that every downstream condition
would pass on the physical FA firmware.

Before dispatch, `0x21d034–0x21d03e` compares the connection security byte at
offset `0x18` with the required level from `0x21eac0`. A lower value is rejected.
Manual branch tracing of `0x21ea60` and `0x21eab0` resolves:

| Decimal opcodes | Required level in FS |
|---|---:|
| 4, 10, 20, 30, 36, 42, 60 | `0x01` |
| **8, 12, 14**, 22, 40, 48, 54, 56 | `0x11` |
| Remaining opcodes in the classification routine | `0x21` |

Classification does not imply that an unknown opcode has an implemented handler.
Live BLE setup returned **33 = `0x21`**, above the FS print-start/file-write
threshold. Live status (8) and capability file-read (40) succeeded at that level.
This reduces concern about the shared gate in this session; it does not replace
a job-acceptance test or explain how a newly paired iPhone would obtain its level.

[The offline verifier](../firmware/trace_ble_transport.py) checks the artifact
hash, configuration pointers, key instructions and dispatcher jump-table entries.
[Its numeric output](firmware-evidence.json) is committed. It disassembles; it
does not emulate execution. The security classification above is a manual branch
trace, not an executed hardware test.

## Physical BLE-only checks and frame audit

Run date: late 2026-11-01 Pacific / 2026-11-02 07:19–07:20 UTC, macOS, existing
paired Select. The temporary bounded harness used `BleConnection` only, an
additional narrow request allowlist, an 8-second scan/request timeout and a
100-second overall timeout. No RFCOMM connection was opened by the harness.
Device discovery/subscription can affect normal radio/connection activity; this
was not an HCI capture or a proof that no other nearby host was connected.

The initial session made four safe exchanges, then stopped because the harness
queried protocol-version attribute 2 instead of SuperModel attribute 9 before
checking the model. This was a harness error, not a printer failure. The corrected
session made 12 successful request/response exchanges and disconnected normally.

| Check | Before / result | After |
|---|---|---|
| Firmware / SuperModel | `G1L1FA2105AR` / `0x48d3` | Same session |
| Connection maximum | 1000 protocol-message bytes | Not a sustained-transfer test |
| Connection security byte | `0x21` (33) | No pairing/security-control operation sent |
| BLE IF_CONFIG | Interface 1; reported protocol MTU **514**; ACK period **0** | Does not establish maximum usable GATT write size |
| Printer / queue / current job | Idle / empty / 0 | Unchanged |
| Battery / power / flags | 100% / charging / 0 | Unchanged |
| Page counter | 13 | 13 |
| Calibration-card cycles | 2 | 2 |
| Capability table | Version 9, protocol 1, 227 table bytes | Includes print start 12, file write 14, resource allocation 48, MIME 1 |

The capability table may describe the printer globally. Its inclusion of print
opcodes is **not** proof of per-transport acceptance. The stronger evidence is
the Android controller path plus the firmware handler dispatch.

The exposed service was `6822d239-7b61-4718-bdc1-189221946209`, with:

- TX `6822d239-7b61-4718-bdc1-de55b3f9051e`: write/write-without-response.
- RX `6822d239-7b61-4718-bdc1-772fa9983658`: read/notify/indicate.
- Pairing/control `6822d239-7b61-4718-bdc1-3dd5acdd2eee`: read property,
  **not read in this investigation**.

The successful session sent **60 application wire bytes in 12 packets** and
received **550 in 12 packets**. All were single-final-fragment envelopes (`0x81`);
the largest RX notification was **234 bytes** (233 protocol bytes, containing the
227-byte capability table). The connected interval was about 1.2 seconds, excluding
scan/connect setup. This is **not a throughput benchmark**. An interim progress
message incorrectly described multiple BLE packets for the capability reply;
the raw frame audit establishes that it was one packet. Fragmented traffic and
ACK pacing remain untested on hardware.

[The offline audit](audit_trace.py) reassembles the recorded wire frames, checks
their matching message records, rejects job/allocation/upload/settings requests,
and scopes capability file reads to the returned handle. The capability read
handle represents read-only table access; it is not a print job or resource
allocation. [The published audit output](trace-audit.json) contains hashes/counts,
not device addresses or identity frames. Raw traces stay in ignored private logs.
The metric named signal strength changed from 50 to 54; other returned metrics
were unchanged. No physical print observation is claimed or needed for this run.

## Probe correction and reproducibility

The audit exposed a latent IF_CONFIG decoding error in the existing probe:
`0b 01 02 02 00` means opcode, interface 1, little-endian MTU 514, ACK period 0.
The old implementation used byte 3 (MTU high byte, 2) as the ACK period. It now
validates the five-byte BLE reply and reads byte 4. All live replies here were
single fragments, so the bug sent no extra ACKs or other commands in these traces.
The fix is regression-tested offline; no additional live session was needed.

From the repository root, with the previously acquired private inputs:

```sh
# Use a Python environment with capstone for the disassembly check.
python experiments/firmware/trace_ble_transport.py logs/color-firmware-research/G1L1FS2105AR_1.0.7.main.bin

# These commands inspect saved files only. No Bluetooth connection occurs.
.venv/bin/python experiments/ble-printing/audit_trace.py logs/20261102T071958Z-ble-feasibility.jsonl logs/20261102T072023Z-ble-feasibility.jsonl
.venv/bin/pytest -q tests/test_ble_config.py tests/test_ble_trace_audit.py tests/test_protocol.py tests/test_capabilities.py
```

The production `BleConnection` still sends only short single-frame requests.
Do not use it as an image-upload transport. No new live experiment command or
general-purpose opcode sender is added by this work.

Validation: the targeted protocol/audit/configuration suite passed **293 tests**;
the full local suite passed **680 tests, 2 skipped**. Lint, formatting of the new
Python files, and whitespace checks passed. The firmware verifier matched the
private hash-pinned image, and both captured sessions passed the offline audit.
The new portable tests also run in the existing macOS/Linux/Windows CI matrix;
that matrix cannot validate Bluetooth hardware behavior.

## Next bounded step

Build a separate, read-only native **CoreBluetooth** path on iPhone (including
the Share extension if available there), reusing the tested message parsers and
durable job core without exposing job submission. Verify discovery, identity,
security level, status and capabilities without External Accessory. Implement
fragmentation and acknowledgement handling with offline tests for packet limits,
sequence errors, disconnects and uncertain writes. Respect both the printer's
protocol budget and the actual platform write limit.

That would answer the most important remaining nonprinting question: can our
own iPhone app use the Select's BLE service with the required session access,
independently of the known-working iAP route? Actual allocation/upload/printing
would require a later separately authorized test. BLE App Store eligibility and
manufacturer-policy questions are not established by these protocol findings.
