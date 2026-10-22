# Select research notes

The current findings are in [INVESTIGATION.md](INVESTIGATION.md). That report
supersedes the tentative cross-device interpretations from the first configuration
probe and records the raw-frame evidence, source provenance, and remaining unknowns.

Confirmed development path:

1. Basic BLE/RFCOMM identity and status probe.
2. Extended configuration, first historical timestamp, GATT/SDP inventory.
3. Static inspection of the HP app artifact, then physical capability-table and
   metrics reads. See the investigation report for corrections to earlier labels.

Key corrections: command `0x3A` reads metrics, feature discovery is `0x2A`,
status fields are enumerated in the device's capability table, and identity tag
`0x0E` is named BornOnDate rather than established first-print time. The current
CLI reports `born_on_timestamp` and source-backed system/battery/queue labels.

Use `probe --extended` for the ordinary snapshot, and `probe --investigate` for
capability/metrics and fixed additional read queries. Neither mode prints or
writes persistent settings. Raw traces, app binaries, and decompiled sources remain
local under ignored `logs/`; committed source is independently implemented Python.

A subsequent [Sprocket 3.0.2921.1 static comparison](NEWER_APK.md) confirms the
core definitions against a newer APK with the same signing certificate. It also
identifies tag 13 as the app's setup-version marker, establishes the app's
"First Print" label for BornOnDate, and records the operator-confirmed ten loaded
sheets and completed orange-card calibration. This follow-up made no device requests.

The operator later authorized non-print setting changes. See
[SETTINGS_RESEARCH.md](SETTINGS_RESEARCH.md) for physically verified sleep/LED
round trips with restoration and additional APK image-processing findings.
Ordinary probes remain read-only; `settings-test` is an explicit separate command.
The sleep/reconnect test is recorded in [VALIDATION.md](VALIDATION.md), and the
completed iOS acquisition and encrypted-code limits is documented in [IOS_EXPLORATION.md](IOS_EXPLORATION.md).

The [naming and device-family reference](NAMING_AND_DEVICE_FAMILIES.md) records
acronym confidence, firmware naming rules, resolved current-APK image profiles,
and the evidence still needed for other printers.
