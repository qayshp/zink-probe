# Sprocket 3.0.2921.1 static comparison

Inspected 2026-10-20 at the operator's request. This was an offline analysis of
downloaded app files: no Android installation, app execution, printer connection,
printer request, print, or settings change was made in this follow-up.

## Artifact and provenance

Downloaded the XAPK served by the [APKPure Sprocket download endpoint](https://apkpure.net/hp-sprocket/com.hp.impulse.sprocket/download).
Its cached web listing was older than the actual download, so the version below
comes from the decoded **base APK's AndroidManifest.xml**, also matching the
bundle manifest, rather than from a search result or filename.

| Property | Observed value |
| --- | --- |
| Package | `com.hp.impulse.sprocket` |
| Version name / code | `3.0.2921.1` / `74251` |
| Minimum / target Android SDK | 23 / 36 |
| XAPK size | 167,241,146 bytes |
| Base APK size | 118,516,014 bytes |
| XAPK SHA-256 | `333fdcf2d386f4d154f534ed6ddb29e6a067fc17ca9b38ace1599305db47bebd` |
| Base APK SHA-256 | `6395bd47fa7c669dd5fbc4a5408a4d54dd8c1841e8581be898f3bf90caaa405c` |
| Signing certificate SHA-256 | `d4091255afab2c804ec73a1af9ef6b8386713028d475c0ac31769230d682c51f` |
| Signing certificate SHA-1 | `4ad089d59175a6ef8bb3943ca5041ab475981532` |

The signing certificate's DER bytes match those extracted from the 2022 APK.
`jarsigner -verify` reports **jar verified** for the new base APK. The certificate
is self-signed; this establishes matching signing identity and a verified JAR/v1
signature, not an independent comparison against a fresh Google Play download or
a complete Android v2/v3 signature audit. The XAPK wrapper itself is not covered
by that base-APK check. No release date is inferred from archive timestamps.

JADX 1.5.6 generated Java from eight DEX files, with 158 reported decompilation
errors across the full app. Resource decoding completed successfully in a separate
pass. The specific classes cited below have usable method bodies, but this is not
a claim that every app method was recovered. The comparison concerns Java/DEX
protocol and app logic, not an exhaustive analysis of native split libraries.

Local evidence is under ignored `logs/`: `vendor-sprocket-current.xapk`,
`vendor-sprocket-current.apk`, `current-decompiled/`, `current-resources/`,
`current-signature-verification.txt`, and `normalized-comparison.txt`.
App binaries and generated vendor Java remain uncommitted.

## Useful additional interpretations

### Attribute 13 is an app setup-version marker

The wire enum still calls tag 13 `SETUP`, but `HPLPPAccessoryInfo` exposes it as
`SprocketAccessoryKey.SETUP_VERSION`. `AddPrinterDialog.onConnectionSuccess`
selects the initial setup path when the key is supported and its value is not 1
(also requiring custom-name and user-color support).

`fragment/add_printer/AddPrinterSetupFragment` writes setup version **1** when the
user completes the name/color setup screen, together with the selected user color
and optional custom name. Therefore the earlier Select response **0** means the
device does not carry this app's version-1 onboarding-completion marker. It does
not establish missing paper, incomplete calibration, or inability to print.
Other setup-version values and reset behavior remain unknown. No marker was set.
The CLI's existing `setup_raw` key is retained to preserve its raw evidence.

### BornOnDate is displayed as First Print

`fragment/DeviceDetailFragment` puts `SprocketAccessoryKey.BORN_ON_DATE` into the
`firstPrint` view. Its layout uses the `first_print` string, whose English value
is **First Print**. Thus the app's user-facing interpretation is now established.

For the earlier Select response, that date is April 11, 2026 at 5:19:44 PM Pacific.
The firmware code that creates the timestamp is not in this APK. We still have
not established whether calibration, a first photo, a reset, or another event
sets or changes it, or whether the clock was correct then. Keep the neutral
`born_on_timestamp` wire-field name and distinguish app labeling from proven
firmware behavior. This app-screen evidence was newly inspected; it is not a
claim that the label was introduced in this release.

### Name length and configuration choices

The app exposes a 32-byte default custom-name limit via
`bt/hplpp/HPLPPConfigurations.getMaxCustomNameSizeBytes`. The name screen applies
`ByteLengthInputFilter`, which uses **UTF-8 bytes**, not a simple character count.
This agrees with the Select's advertised name limit of 32. The device's actual
acceptance boundary, including multibyte names, remains untested.

The shared HPLPP configuration UI offers sleep off / 3 / 5 / 10 minutes, and
automatic power-off off / 1 / 2 / 5 hours. These are app choices, not proof the
Select rejects other wire values. The previously read 3-minute sleep and
60-minute power-off match those choices. No options were changed.

### Resource 1 is job color

`HPLPP/messages/model/Resources` defines identifier 1 as `JOB_COLOR`. This gives
a source-backed name to the Select's advertised resource list `[1]`. Allocating
that resource is a state-changing operation and remains outside the probe.

## What the comparison confirms

After removing block comments and whitespace, **80 of the 97 historical HPLPP
Java classes** are textually identical to their new counterparts. All 97 have
counterparts; most remaining differences are compiler-generated lambda names,
constant substitutions, generic casts, or transport/application changes.
This is a source-text comparison, not formal binary equivalence.

- Identity/status/config enums, typed response parsers, system-flag masks,
  battery and queue enums, discovery/read-file messages, and metrics request and
  response schemas retain the definitions used by our probe.
- `fw_counters.json` has the same labels and identifiers. Its only textual change
  is removal of an invalid trailing comma after `printer_pages` in the old file.
- Feature-table tag declarations and parsing schema are unchanged; differences
  in that class are generated lambda annotations/names.
- `SprocketDeviceType.GRAND_BAHAMA` still uses **768 × 1152**, JPEG quality **90**,
  and paper label **2.3 × 3.4**. This remains an app input profile, not measured
  native printer resolution or a physically verified print result.
- `GrandBahamaDevice` exposes remote queue and actions, and gates background
  firmware update / update-on-shutdown on the reported feature table. Its fallback
  feature table is not a replacement for the actual Select capability download.

## Substantive newer code and its limits

`HPLPP/BLEcommClient` now explicitly creates/waits for an Android Bluetooth bond
before GATT connection, polling at 200 ms for up to 120 seconds. It cancels active
Classic discovery first, opens GATT on the main thread, and adds a two-second
settling delay after a new bond on Google Pixel builds. This is concrete evidence
of Android connection handling changes. It is not a macOS requirement or a proven
explanation of our earlier optional pairing-characteristic timeout.

New HPLPP classes include `BleTrafficLog` and two classes named
`PrintCutWriteSystemConfig...`. The latter serialize an existing configuration
write to `USER_COLOR`; the caller packs its argument into an RGB byte. Their names
do not establish a Select cutter or a safe query. The newer app handles multiple
printer families, and our probe does not implement or send these writes.

## Paper state and unresolved questions

The operator confirms a **new pack of ten ZINK sheets is loaded**, and that the
**orange calibration card was already processed and discarded**. This is physical
ground truth supplied after the earlier read-only investigation, not a fresh
device measurement. The earlier printer-pages value 10 is a reported counter,
not the number of sheets currently loaded. Earlier zero pages-since-cover and
pages-since-calibration values are consistent with a freshly loaded/calibrated
pack, but cannot establish its remaining sheet count by themselves.

The newer HPLPP `StatusFields` enum still ends at tag 9 and `SystemConfigAttribute`
still ends at tag 5. It supplies no Select remaining-sheet count or calibrated-card
inventory field. This does not prove the firmware has no additional private fields;
it means this inspected library does not resolve the unadvertised supply fields.

Still unresolved: the connection security byte `0x21`, detailed security-mode enum
meanings, target-event payloads, and the passive channel-1 beacon. The newer
`TargetEventMessage.deserializeMessage` still ignores its payload. Searches of
the recovered HP Java sources did not identify the observed beacon's hex string
or custom service UUID; that negative search is not proof they are absent in
other forms or native libraries. No unsupported interpretations were added to
the probe, and no additional live testing was performed in this follow-up.
