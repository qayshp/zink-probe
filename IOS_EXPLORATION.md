# Bounded iOS package exploration

Started 2026-10-21 at 08:17 UTC, with an upper bound of one hour (09:17 UTC).
The preceding sleep test is recorded separately in [VALIDATION.md](VALIDATION.md).
This follow-up does not authorize printing or printer-setting changes.

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

## Acquisition work

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

No iOS Sprocket executable has yet been obtained, launched, disassembled, or
decrypted in this exploration. A metadata catalog or queued blueprint is not a
successful IPA download. Package encryption and current iOS protocol behavior
cannot be assessed until an actual artifact is acquired.

Outcome: the cache watcher reached the 09:17 UTC deadline and exited without
capturing an IPA. Model availability interrupted active work before then; this
was not an hour of completed binary analysis. The operator subsequently deferred
the separate download-tool authentication until later. No further acquisition
or login is attempted in the non-print settings follow-up.

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

## Next artifact checks

If acquisition succeeds within the time limit, inspect the bundle identity and
version, archive fingerprint, ExternalAccessory/BLE declarations, bundled printer
frameworks, Mach-O encryption load commands, and accessible symbols/resources.
Native executable encryption may limit code recovery; it must be checked on the
artifact rather than assumed. All binaries, generated metadata, and any
account-associated archive contents must remain local and ignored by Git.
