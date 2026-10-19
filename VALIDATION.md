# Milestone 1 validation

## Software checks completed

- Editable package install on macOS, Python 3.14.
- CLI entry point/help.
- IOBluetooth framework import, delegate initialization, and availability of the
  native RFCOMM channel-open selector.
- 275 automated cases, including rejection of 252 disallowed command opcodes.
- Ruff lint and formatting checks.
- Live discovery failure recorded as a JSON result and private JSONL trace.

## Initial live attempt

CoreBluetooth reported authorization `0` (not determined). A scan did not return
within its initialization deadline. This establishes an authorization/initialization
block, not a device compatibility failure or evidence that the printer was absent.
No physical Select protocol response was received.

## Hardware acceptance still required

- [ ] BLE discovery identifies the Select and retains its raw service data.
- [ ] Identity read confirms SuperModel `0x48D3`.
- [ ] BLE reads return firmware, battery, printer state, and Bluetooth MAC.
- [ ] MAC read maps to the intended paired Classic Bluetooth device.
- [ ] RFCOMM channel 2 opens while BLE stays connected.
- [ ] RFCOMM reads return matching Select identity, firmware, battery, and status.
- [ ] Raw TX/RX frames and decoded results are retained for both transports.
- [ ] Failure and operator interruption release both owned connections.
- [ ] No settings or print commands occur in the recorded transcript.

Do not mark hardware acceptance complete from simulated tests. Record exact
firmware, host/runtime versions, observations, and the private trace location when
the physical probe succeeds. Keep hardware identifiers and traces out of Git by
default.

