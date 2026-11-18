# Physical iPhone CoreBluetooth validation — 2026-11-18

**All four app/process contexts completed the fixed read-only BLE sequence
against the physical Select:** the isolated Select BLE Check app and Share
extension, and the existing Select Probe app and Share extension. Each result
is recorded separately below.

Evidence is a **manual transcription of the report displayed through iPhone
Mirroring**, observed by the controlling agent. The Mac accessibility tree exposed
the Mirroring window rather than the phone's individual controls/report text.
This is neither an exported application log nor a raw GATT/HCI frame capture.
Private screenshots and phone-library images are not published here.

The implementation was introduced in commit `1551778`; the isolated app has fresh
bundle identifiers and links CoreBluetooth without ExternalAccessory. It contains
no photo preparation, print engine, saved jobs, External Accessory protocol
declarations or background Bluetooth mode. Its Share extension ignores shared
image content. See [the isolated-product notes](../BLEOnlyProbe/README.md) and
[the diagnostic boundary](../BLE_CHECK.md).

## Results by process

| Product / process | Build | Result | Boundary |
|---|---:|---|---|
| Select BLE Check / main app | 1 | **Passed** | Physical standalone CoreBluetooth reads in the phone's existing pairing environment |
| Select BLE Check / Share extension | 1 | **Passed** | Physical standalone CoreBluetooth reads inside the Photos-hosted extension |
| Select Probe / main app | 15 | **Passed** | Comparison app also declares the existing External Accessory route |
| Select Probe / Share extension | 15 | **Passed** | Separate comparison process, opened from Photos and using CoreBluetooth |

## Isolated main-app run

All times below are UTC on 2026-11-18 (Pacific local time is eight hours earlier).

| Observed event | Reported time |
|---|---|
| Explicit scan requested; initial Bluetooth authorization raw value 0 | 16:19:43 |
| Bluetooth permission approved in the system prompt | 16:19:53 |
| Scan ended with one candidate, signal -46 dBm | 16:20:03 |
| Explicit read-only connection requested | 16:20:16 |
| RX subscription and native write limit reported; configure/firmware/model phases | 16:20:17 |
| Setup, before-status, feature/download, after-status and completion | 16:20:18 |

| Reported field | Value |
|---|---|
| Firmware | `G1L1FA2105AR` |
| SuperModel | `0x48d3` |
| Native write-with-response limit | 512 bytes |
| Peer protocol-message maximum | 1000 bytes |
| Connection security byte | 33 / `0x21` |
| Protocol MTU | 514 bytes |
| Negotiated acknowledgement period | 0 |
| Capability-table size | 227 bytes |
| Advertised request opcodes, decimal | `4,6,8,10,12,14,16,18,20,22,24,26,28,32,34,36,38,40,42,44,46,48,50,52,54,56,58` |
| GATT TX queued / acknowledged | 40 / 40 bytes |
| Successful native write callbacks | 8 |
| GATT RX | 314 bytes |

The write callback count and byte totals match the expected short eight-request
diagnostic exchange. A GATT write acknowledgement is not a print acknowledgement.
These totals and the short elapsed interval do not measure sustained transfer
speed, prove a complete image-upload path, or establish fragmented transfers.
The protocol MTU and platform write limit are distinct values.

Before and after status were identical:

| Status | Before | After |
|---|---:|---:|
| Battery percentage | 99 | 99 |
| Power code | 1 (in use / not charging) | 1 |
| Printer state | 1 (idle) | 1 |
| System flags | `0x00000001` | `0x00000001` |
| Current job | 0 | 0 |
| Queue state | 1 (empty) | 1 |
| Hosts field | 0 | 0 |

Flag bit 0 is the source-backed **time-invalid / clock-invalid** flag. It was
reported and **left unchanged**; no clock synchronization or other corrective
write was performed. This diagnostic intentionally reports busy/error/security
conditions without treating successful reads as print readiness. The hosts
field is a protocol observation, not independent proof that no other host had a
connection.

## Existing-app comparison run

Select Probe Build 15 was tested separately after the isolated main-app run.
Its Bluetooth permission was also approved through the normal system prompt;
no other permission setting or pairing record was reset. Its report recorded:

| Observed event | UTC on 2026-11-18 |
|---|---|
| Explicit scan requested; initial authorization raw value 0 | 16:21:24 |
| Bluetooth permission approved | 16:21:38 |
| Scan ended with one candidate, signal -46 dBm | 16:21:48 |
| Explicit read-only connection requested | 16:21:54 |
| RX subscription and native write limit 512 bytes | 16:21:55 |
| Fixed sequence completed | 16:21:56 |

All reported protocol values, capability size/request list, before/after status
and byte counts matched the isolated main-app run: firmware FA2105, model
`0x48d3`, maximum 1000, security 33, protocol MTU 514, ACK period 0, capability
table 227 bytes, 40 TX queued/acknowledged bytes, eight write callbacks and
314 RX bytes. Battery remained 99%, power 1, printer idle, queue empty, current
job 0, hosts 0, and the unchanged clock-invalid flag `0x00000001` was reported.

This comparison confirms that the common CoreBluetooth code worked in both
main-app identities in these runs. It does not establish that declaring External
Accessory has no possible effect in every pairing or authorization environment.

## Existing Share-extension run

Select Probe's Build 15 Share extension was opened from Photos with one image
selected. Its BLE diagnostic used CoreBluetooth; no External Accessory session
was opened for this check. Initial Bluetooth authorization raw value was 3,
and no additional permission prompt appeared.

| Observed event | UTC on 2026-11-18 |
|---|---|
| Scan requested and Bluetooth reported powered on | 16:23:50 |
| Scan ended with one candidate, signal -40 dBm | 16:24:00 |
| Explicit read-only connection requested | 16:24:31 |
| RX subscription and native write limit 512 bytes | 16:24:35 |
| Fixed sequence completed | 16:24:36 |

All reported protocol/capability/status values and traffic counts matched the
two main-app runs above, including the unchanged clock-invalid flag. TX queued
and acknowledged were both 40 bytes with eight successful native write callbacks;
RX was 314 bytes. This establishes a completed physical read-only BLE session
inside this Share extension in the tested foreground Photos-host environment.
It does not establish background or interrupted-extension behavior.

## Isolated Share-extension run

The Select BLE Check Build 1 Share extension was opened from Photos with one
image selected. Its implementation ignores the image content. The user assisted
only with horizontal navigation to its Share-sheet app entry; the controlling
agent then ran the explicit scan/read-only check and observed the result through
iPhone Mirroring. No app-code change was needed. Initial Bluetooth authorization
raw value was 3, and no additional permission prompt appeared.

| Observed event | UTC on 2026-11-18 |
|---|---|
| Scan requested and Bluetooth reported powered on | 16:30:35 |
| Scan ended with one candidate, signal -44 dBm | 16:30:45 |
| Explicit read-only connection requested | 16:30:52 |
| RX subscription and native write limit 512 bytes | 16:30:53 |
| All fixed protocol phases and completion | 16:30:53 |

Reported firmware, model, maximum, security byte, protocol MTU, ACK period,
capability-table size/request list and traffic counts matched the other three
runs: FA2105, `0x48d3`, 1000, 33, 514, 0, 227 bytes, 40 TX queued/acknowledged
bytes, eight write callbacks and 314 RX bytes. Its before/after battery snapshots
were both **98%**, compared with 99% in the earlier three runs. No cause for that
change across elapsed time is inferred. All other queried status fields matched:
power 1, state 1, flags `0x00000001`, current job 0, queue 1 and hosts 0.

This establishes a complete foreground read-only BLE session in the isolated
Share process without that product linking or declaring External Accessory.
The earlier navigation difficulty was a Mirroring/Share-sheet interaction issue;
no BLE failure was observed in this context.

## What this establishes and leaves open

The observed standalone signed app and Share extension could discover the
service, use normal Bluetooth permission, connect, subscribe and complete
firmware/model, session negotiation, status and capability reads on the physical
FA printer. The existing Select Probe app and Share process completed the same
sequence. All reports agreed with the source-backed protocol shape and earlier
Mac read-only values for firmware, model, maximum, security byte, protocol MTU
and capability size. There was no observed BLE failure in these four completed
runs. This does not establish universal connection reliability.

The fixed diagnostic implementation has no job-allocation, image-upload,
print-start, clock, persistent-settings, pairing-control or fast-BLE request.
No such command was invoked for this run. Capability discovery returns a
read-only table handle; this is not a print-job/resource allocation. The report
did not query page/calibration counters, so no counter-based no-print proof is
claimed. No physical print or paper-consumption experiment was performed.

Still unverified: never-paired phone onboarding; repeated/recovery behavior;
background/interrupted Share-host behavior; competing connections; sustained transfer;
BLE job acceptance/upload/printing; and App Store eligibility. The iPhone's
existing pairing history was retained. No unpairing or reset was used to make
the test pass. An app without ExternalAccessory linkage does not erase the
phone's pre-existing accessory/pairing state.

The sanitized, structured transcription is
[2026-11-18-physical-results.json](evidence/2026-11-18-physical-results.json).
It contains no device UUID, address, serial, private screenshot or shared image.
