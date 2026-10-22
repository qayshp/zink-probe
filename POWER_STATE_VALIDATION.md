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
`20261022T075908.530150Z-probe.jsonl`. Unplug/replug validation is pending operator confirmation;
no conclusion about those transitions is drawn from this baseline alone.
