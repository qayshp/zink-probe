# Milestone 1 validation

## Software checks completed

- Editable package install on macOS, Python 3.14.
- CLI entry point/help.
- IOBluetooth framework import, delegate initialization, and availability of the
  native RFCOMM channel-open selector.
- 276 automated cases, including rejection of 252 disallowed command opcodes and
  a regression case for the physical Select's fixed-width identity fields.
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
