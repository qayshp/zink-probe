# Bounded iOS package exploration

The first pass started 2026-10-21 at 08:17 UTC, with an upper bound of one hour
(09:17 UTC). Official package acquisition succeeded in a later resumed pass on
2026-10-22 UTC (the evening of October 21 in America/Los_Angeles); see below.
The preceding sleep test is recorded separately in [VALIDATION.md](VALIDATION.md).
No printing was performed. Subsequent authorization for reversible printer
settings is recorded separately in [SETTINGS_RESEARCH.md](SETTINGS_RESEARCH.md).

## Current official app identity

Apple's [App Store listing](https://apps.apple.com/us/app/hp-sprocket/id1132331237)
and its public lookup response identify:

| Field | Value |
| --- | --- |
| App ID | `1132331237` |
| Bundle ID | `com.hp.sprocket` |
| Version | `2.80.56` |
| Release timestamp in lookup response | `2026-07-20T07:29:30Z` |
| Minimum iOS | `15.6` |
| Reported package size | `473409536` bytes |

The release notes describe a Studio Plus connection fix. Version numbers across
the iOS and Android apps are separate and do not establish protocol parity or
which platform has newer Select behavior. This metadata is not a downloaded IPA
or a verified executable version.

Private lookup response: `logs/sprocket-ios-lookup.json`.

## First acquisition pass

- Apple Configurator 2.21 is installed. It initially had no signed-in account;
  the operator completed Apple Account authentication locally. No password was
  sent through this chat or recorded in project files.
- The authenticated app catalog lists Sprocket 2.80.56. A temporary blueprint
  named **Zink IPA Research** contains this one app action. It was not applied
  to any device and contains no prepare, erase, restore, or update action.
- Adding an app to a blueprint stores an action rather than downloading the IPA.
  This matches Apple's [Add apps to a device documentation](https://support.apple.com/guide/apple-configurator-mac/add-apps-to-a-device-cad4cd08c03/2.21/mac/15.7).
  The next dependency is a connected, trusted iOS device for this route.
- [ipatool](https://github.com/majd/ipatool) 2.7.0 was downloaded from its official
  release, extracted locally under ignored `logs/`, and its archive SHA-256
  checked against GitHub's release metadata:
  `5ae100d4520cf4b3f4374239e5925a9ad9a8dc02abc16bae27479e7ae99aca33`.
  It has no existing account in its tool-specific keyring; a noninteractive
  Sprocket download attempt stopped at that missing account. Configurator's
  authenticated session does not automatically create an ipatool session.
- No Sprocket IPA was found in the Configurator cache, Downloads, or the targeted
  Spotlight filename search. Public GitHub/source/archive searches did not yield
  a current IPA. One public catalog returned HTTP 403; a legacy catalog URL
  redirected to an unrelated generic site and supplied no package. Those results
  are acquisition failures, not evidence of device/protocol limitations.

At the end of that first pass, no iOS Sprocket executable had been obtained,
launched, disassembled, or decrypted. A metadata catalog or queued blueprint was
not a successful IPA download.

Outcome: the cache watcher reached the 09:17 UTC deadline and exited without
capturing an IPA. Model availability interrupted active work before then; this
was not an hour of completed binary analysis. The operator subsequently deferred
the separate download-tool authentication until later. No further acquisition
or login was attempted in the non-print settings follow-up.

## Resumed official acquisition: successful

The operator subsequently connected an iPhone. Configurator could inspect its
apps without a new authentication or Trust prompt. A narrowly filtered local
inventory confirmed that `com.hp.sprocket`, build `25`, was already installed.

Using **Add > Apps > sprocket** downloaded the official package and reached an
explicit existing-app dialog offering **Replace**, **Skip App**, and **Stop**.
While this dialog was pending, the package was copied out of Configurator's
temporary cache and verified. **Stop** was then selected; **Replace** was never
selected. No blueprint was applied, and no app installation, phone preparation,
erase, restore, or printer command was performed in this acquisition pass.
A second local inventory after cancellation still reported Sprocket build `25`.

| Acquired artifact field | Observed value |
| --- | --- |
| Bundle ID | `com.hp.sprocket` |
| Marketing version | `2.80.56` |
| Build | `25` |
| Minimum iOS | `15.6` |
| Actual saved archive size | `374138724` bytes |
| SHA-256 | `7581bea994ca9cf844bf7fa0ebd18d4c8ebca6d55208fbfaabee321375cd6517` |
| Archive verification | ZIP member CRC checks passed before and after copying |

The saved archive's size differs from the public lookup's reported size. The
bundle metadata above comes from the actual downloaded package, rather than
assuming the catalog's size describes this particular delivered artifact.

In this Configurator version, the cached ZIP had the filename `1132331237`, with
**no `.ipa` extension**. The initial filename-only watcher missed it; inspecting
large cache files by their ZIP contents located it while the replacement dialog
kept it available. Future capture tooling should verify bundle identity and
archive completeness instead of depending on an `.ipa` suffix.

Private evidence remains under ignored `logs/`: `vendor-sprocket-ios.ipa`,
`ios-ipa-acquisition.json`, and `ios-inspection/`. The archive, cache paths,
device identifiers, complete phone app inventory, and account-associated files
are not published in Git.

## What the acquired package establishes

The main bundle declares four ExternalAccessory protocol identifiers:
`com.hp.protocol.bahama`, `com.hp.protocol.lifestyle`, `com.hp.protocol.maui`,
and `com.hp.protocol`. It also links both CoreBluetooth and ExternalAccessory
and declares Bluetooth access plus the external-accessory background mode.
These establish app declarations and linked APIs; they do not establish which
transport this iOS build actually selects for a particular Select printer.
In particular, the `bahama` name alone is not a decoded GrandBahama command map.

The bundle includes `CPPrinterSDK.framework`, together with ImglyKit,
PhotoEditorSDK, MedalliaDigitalSDK, and AirshipAppExtensions frameworks. The main
executable imports CPPrinterSDK classes for BLE, Wi-Fi/network configuration,
sessions, and discovery. This is a multi-printer app: the presence of those APIs
does **not** establish Wi-Fi or those other models' paper sizes on the Select.

Readable interface resources include printer identity/battery/firmware labels,
auto-off choices, printing/error states, and connection-debug views. They do not
provide numeric wire-field offsets, flag-bit assignments, or a Select-specific
resolution conversion. Compiled interface resources can retain unused or older
screens, so their presence does not prove a reachable app feature or device
support.

## Encryption limits and unresolved questions

All eight inspected Mach-O binaries declare `LC_ENCRYPTION_INFO_64` with
`cryptid = 1`: the main executable, five frameworks, the print extension, and the
notification extension. For the main executable the marked range starts at
file offset `16384` and covers `20905984` bytes; for CPPrinterSDK it starts at
`16384` and covers `131072` bytes. The inspected main/CPPrinterSDK method-name,
class-name, and C-string sections fall within their respective encrypted ranges.

Load commands, imported symbols, bundle metadata, and separate resources remain
inspectable. Disassembling the encrypted instruction bytes as if they were
plaintext would not recover valid command logic. No decryption, executable
patching, jailbreak, or vendor binary execution was performed.

This pass therefore **does not resolve**:

- additional Select protocol commands, security-byte meaning, target-event
  payloads, or the Classic channel-1 beacon;
- the current iOS app's exact Select resize/JPEG/PhotoFix pipeline;
- whether Select firmware accepts arbitrary input image dimensions;
- how the Android app's `768 × 1152` input raster maps to the published
  `321 × 600 dpi` specification or to physical heating/advance positions.

The Android source evidence and earlier physical read/configuration tests remain
the stronger evidence for those respective paths. Obtaining the official IPA is
a completed acquisition milestone, not a successful recovery or physical
validation of its encrypted printer implementation.

## Historical iOS source found

The public [rtauseef/sprocket_ios_app repository](https://github.com/rtauseef/sprocket_ios_app)
has snapshot `2148910014664dfa4b80b301fb5977d2519739d3`, dated 2017-07-17.
Selected printer-related Objective-C files were downloaded as data under
`logs/historical-ios/`; no project build or vendor app execution was performed.

Its Podfile pins MobilePrintSDK 3.0.10 from the historical
`IPGPTP/ios-print-sdk` Bluetooth branch. That upstream URL currently returns 404.
The separately accessible [mobileprint/ios-print-sdk](https://github.com/mobileprint/ios-print-sdk)
repository also has an older Bluetooth branch.

The inspected factory dispatches to **Manta** and **Maui** implementations.
Those use fixed 34-byte request packets beginning `1b 2a` and iOS
ExternalAccessory protocol strings such as `com.hp.protocol` and
`com.hp.protocol.maui`. They are distinct from our Select's HP+ RFCOMM framing
and current BLE protocol. The downloaded files do not provide Select/GrandBahama
HPLPP implementations or resolve its security byte, target events, or beacon.
No older packet command was tried on the Select.

Treat this as historical implementation evidence, not an authenticated current
vendor SDK or physical Select validation. Vendor source is not copied into this
repository or used as a runtime dependency. Local per-file fingerprints are in
`logs/historical-ios-artifacts.json`.

## Artifact checks completed

The resumed pass checked bundle identity/version, archive fingerprint and CRCs,
ExternalAccessory/BLE declarations, bundled printer frameworks, Mach-O encryption
load commands, and accessible symbols/resources. The concrete encryption limits
and remaining protocol questions are recorded above. All binaries, generated
metadata, and account-associated archive contents remain local and ignored by Git.


## Independent iOS app follow-up — 2026-10-26

The [read-only accessory probe](ios/README.md#physical-session-result--2026-10-26)
was built and installed under our own app identity. The user supplied a physical
report confirming discovery of the Select (`HPISPSLE`, `G1L1FA2105AR`, hardware
`4138`) and successful opening of both EASession streams for its advertised
`com.hp.protocol.lifestyle` protocol. Application TX=0 and RX=0; no printing.
This resolves basic session accessibility for this development build/device,
but not printer-command framing or production-distribution authorization.
