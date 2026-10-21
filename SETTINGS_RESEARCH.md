# Non-print settings and targeted APK follow-up

On 2026-10-21 the operator explicitly authorized printer-setting changes while
continuing to prohibit printing or wasting paper. The implemented experiment
temporarily changes only sleep time and a standard LED color, restoring each.
The existing read-only probe commands keep their default policy.

## Source evidence and implementation

The previously fingerprinted Sprocket Android 3.0.2921.1 artifact defines
`WriteSystemConfigRequestMessage` as command `1C`, with typed field bytes:

- Field `01`: sleep time, uint16 little-endian minutes.
- Field `03`: user color, three bytes in red/green/blue order.
- Response command `1D`; its deserializer consumes no fields.

Source classes: `HPLPP/messages/WriteSystemConfigRequestMessage`,
`WriteSystemConfigurationResponseMessage`, and `SprocketByteBuffer`. See
[NEWER_APK.md](NEWER_APK.md) for artifact provenance. The Python implementation
is independent; vendor source and binaries are not distributed here.

`settings-test` grants the exact desired and original request bytes only during
one transaction. A second policy check permits only the four app-defined sleep
choices (0/3/5/10) or the six standard Select RGB colors. Arbitrary RGB encodings
are deliberately excluded: the newer multi-printer app also has a misleadingly
named PrintCut class that packs values into that configuration field. This is
not a reason to assume every RGB byte combination is harmless on every model.

Both transport identities and baseline configurations must match. The printer
must be idle with an empty queue, advertise configuration writes and the relevant
fields/colors, and provide page and calibration counters before any mutation.
Unsupported original values cause an abort before mutation, since restoration
must itself fit the scoped policy. The baseline and grants are logged privately.

## Physical results

Firmware `G1L1FA2105AR`, Select model `48D3`, capability version 9:

| Experiment | Write transport | Temporary readback on both transports | Restore transport | Restored readback on both |
| --- | --- | --- | --- | --- |
| Sleep timer | BLE | 5 minutes (original 3) | RFCOMM | 3 minutes |
| LED color | RFCOMM | `#002ee0` blue (original white) | BLE | `#ffffff` white |

Every write returned `1D`. The tested request bodies were:
`1c010500`, `1c010300`, `1c03002ee0`, `1c03ffffff`.
Both settings are therefore visible globally across the two connections, rather
than merely cached within the writing transport. This is protocol readback;
the physical LED appearance was not observed by the agent.

Full final configuration matched the baseline: sleep 3 minutes, auto-off Never
(`0`), white LED, pause 0, host threshold 3. A separate fresh discovery/connection
and investigation confirmed these original values again on BLE and RFCOMM.
Printer-pages remained 10 and calibration-card cycles remained 2 throughout both
sessions. No paper count is inferred from those counters.

The settings session contained **137 application requests**, exactly **four**
of them configuration writes. An independent trace audit checked every request
against the read-only policy plus the currently granted exact writes; all grants
and capability handles were revoked, and no cleanup error was recorded.
The fresh read-only reconnect session completed successfully as well. There were
no target-event messages in the settings trace, so these setting changes did not
resolve the payload semantics of earlier unsolicited events.

No print start, file upload, resource allocation, pause/resume, clock, security,
setup-marker, trigger, reset, or firmware command was sent. No persistent setting
change remains from this experiment. We did not inject a physical disconnect or
power loss while a setting was temporarily changed.

Private evidence:

- `logs/settings-roundtrip-live.json` and
  `logs/20261021T193759.709331Z-settings-test.jsonl`.
- `logs/settings-test-audit.json`: exact writes, transport counts, grant audit.
- `logs/settings-post-reconnect.json` and
  `logs/20261021T193924.000383Z-probe.jsonl`: restoration after reconnect.

## Additional static findings

The Android app's `HPLPP/MessageClient.runSetup` queues a time-setting request.
`SetTimeRequestMessage` serializes an epoch timestamp and signed timezone offset;
`SprocketByteBuffer` uses little-endian order. This establishes automatic clock
setting in this Android code path. It is consistent with, but does not prove the
cause of, the previously observed cleared time-invalid bit after phone use.
The phone's iOS exchange was not captured. Our probe did not set the clock.

Native-library triage of the same APK's arm64 split identified:

- `libhporb`: Java bindings for image feature tracking/training and Lanczos resize.
- `libmatterhorn`, reached through the `rlt_jni_small` bridge: PhotoFix image
  enhancement, with bitmap input/output and enhancement-mode parameters.
- `libxeno_native`: loaded by Google's vision/MediaPipe-related Java code.

`services/PreprocessPrintService.createPrintBitmap` obtains the device's target
size and attempts default PhotoFix if the input is not already marked enhanced.
`ImageUtil.applyPhotoFix` returns false on failure; this caller does not check that
return value before continuing with the bitmap. Its debug log can therefore say
"applied=true" even if enhancement failed. Consequently, this code path does not
make successful proprietary enhancement a hard prerequisite for further image
processing. It does not establish identical colors without PhotoFix or physical
printing compatibility of any independently prepared JPEG.

These libraries were extracted and inspected as data, not loaded or executed.
Text searches of the three inspected native binaries did not identify HPLPP,
GrandBahama, or the observed custom beacon. This was limited triage, not exhaustive
native disassembly or proof that a behavior is absent. The Java implementation
remains the strongest recovered protocol evidence. Security byte `21`, detailed
security-mode meanings, target-event payloads, and beacon fields remain unknown.

## Verification and deferred work

314 automated tests pass, including default write rejection, exact grant expiry,
rejection of unsafe/malformed grants, restoration after a lost acknowledgement or
cancellation, failure reporting when restoration cannot be verified, busy-printer
refusal, and preflight rejection of unrestorable original values/missing counters.
Ruff lint/format and dependency checks pass. Failure paths are synthetic tests;
the successful settings round trips and fresh readback are physical validation.

The prior sleep/reconnect result and iOS acquisition notes are now retained in
the repository. IPA authentication/acquisition remains deferred at the operator's
request; no IPA or new iOS binary analysis was obtained in this follow-up.
