# Live power-state follow-up

2026-10-22 UTC. The operator confirmed the Select was nearby and connected to
micro-USB power and authorized non-print communications. This session used the
existing bounded investigation, 30-second observation, and passive channel-1
listener. No settings writes or printer job commands were sent.

## Plugged-in baseline

Both BLE and RFCOMM completed successfully. Three observation samples over the
30-second window agreed on 100% battery, battery status 2 (`charging`), idle,
empty queue, and zero system flags. This is the firmware's label at full reported
charge, not a measurement of current flowing into the battery.

Configuration and the complete capability table matched the prior successful
post-settings reconnect snapshot. Sleep remained 3 minutes, auto-off Never (0),
LED white, pause 0, and host threshold 3. Counters read:

| Metric | Both transports |
| --- | ---: |
| Printer pages | 10 |
| Calibration-card cycles | 2 |
| USB attach events | 17 |
| Battery level before charge | 99 |
| Sleep events | 43 |
| Power-on events | 16 |

The signal-strength field differed between transports (46 BLE, 128 RFCOMM).
Its units, signedness, and sentinel semantics remain unproven; do not treat
these numbers as calibrated RSSI or percentages.

Passive RFCOMM channel 1 delivered six instances of `ff550200ee10` during its
five-second listen and transmitted zero bytes. No new target events were logged.
An independent audit reconstructed every transmitted application message from
wire frames: 51 BLE and 55 RFCOMM requests, all allowed by the existing read-only
policy (including scoped capability-file reads). There were zero configuration
writes. Raw identity and frame traces remain private under ignored `logs/`.

Private evidence: `plugged-baseline-20261022.json`, its `-audit.json`, and
`20261022T075908.530150Z-probe.jsonl`.


## Confirmed unplugged comparison

After the operator confirmed removal of the micro-USB cable, a fresh bounded
investigation and 30-second observation completed on both transports. All three
observation samples reported 99% and battery status 1 (`in_use`), compared with
100% and status 2 (`charging`) in the plugged-in baseline. This physically
validates the two enum labels for this unit and these conditions. It does not
measure charge current, battery capacity, transition latency, or discharge rate;
the one-point change alone cannot establish any of those quantities.

Configuration and capability tables were identical to the plugged-in baseline.
USB attach events stayed at 17; battery level before charge stayed at 99.
Printer pages stayed at 10, calibration cycles at 2, and power-on events at 16.
The only metric change on either connection was sleep events 43 → 44. An idle
interval occurred between sessions, so the increase cannot be attributed
specifically to unplugging. Both connections reported idle/empty and zero flags.

A second wire-message audit passed all 106 application requests (51 BLE, 55
RFCOMM), with zero settings writes. No passive beacon listen was included in
this unplugged run. Private evidence: `unplugged-20261022.json`, its `-audit.json`,
and `20261022T080254.035527Z-probe.jsonl`.

## Confirmed charger reconnection

After the operator confirmed reconnection, the first attempt read BLE status
successfully (99%, charging) but failed on the initial RFCOMM negotiation write
with `IOReturn -536870169`. That attempt returned failure and did not complete
metrics collection. One fresh probe session then completed on both transports.
The cause of the transient Classic Bluetooth failure is unknown; reconnection
succeeded without changing permissions, pairing, settings, or probe code.

All three observations in the successful 30-second window reported 99% and
battery status 2 (`charging`) on both transports. The controlled sequence is:

| Reading | Initially plugged in | Unplugged | Reconnected |
| --- | ---: | ---: | ---: |
| Battery percentage | 100 | 99 | 99 |
| Battery status enum | 2 (charging) | 1 (in use) | 2 (charging) |
| USB attach events, metric 7 | 17 | 17 | 18 |
| Battery level before charge, metric 8 | 99 | 99 | 99 |
| Printer pages | 10 | 10 | 10 |
| Calibration-card cycles | 2 | 2 | 2 |

Metric 7 increased by exactly one after the single confirmed reconnection and
agreed across BLE/RFCOMM, physically supporting its USB-attachment-counter label.
Metric 8 was already 99 before unplugging; reconnecting at 99% therefore does not
distinguish refresh-at-attachment from an unchanged historical value. The test
also does not establish counter persistence across power loss or reboot.

Configuration and capability tables remained identical. Sleep events stayed at
44, power-on events at 16, and both transports reported idle, empty queue and
zero system flags. The BLE signal-strength metric changed 46 → 58 while RFCOMM
remained 128; its units/sentinel interpretation remain unresolved.

The successful session's 106 application requests (51 BLE, 55 RFCOMM) passed the
read-only wire-message audit. The failed session logged 29 attempted application
writes (28 BLE, one RFCOMM negotiation request), also all within policy; the failed
RFCOMM write log does not establish delivery. Neither attempt included settings
writes or printing commands. No target events were logged. These snapshots do
not measure the immediate transition latency or establish notification behavior
while a connection stays open through unplugging.

Private evidence: `replugged-20261022.json` (failed attempt),
`replugged-retry-20261022.json` (successful), their `-audit.json` files, and traces
`20261022T080539.964858Z-probe.jsonl` and
`20261022T080631.213065Z-probe.jsonl`. No additional unplugging is needed for this
comparison; the printer was left connected to its charger.

## Later print-state observation

The [authorized CAL-02 print](experiments/calibration/FIRST_PRINT.md) reported
charging → in_use during printing → charging afterward. Charger continuity is
pending operator confirmation. The earlier unplug/replug result validates those
idle conditions; it does not establish battery status as a universal USB-presence
indicator or a measurement of charging current.
