# Acronyms, names, and future device families

Reviewed 2026-10-21. This is a research map, not a supported-printer list.
Only one HP Sprocket Select has been physically validated by this project, for
identity/status/configuration reads and the documented reversible settings tests.
No physical printing has been validated. See [VALIDATION.md](VALIDATION.md).

## Evidence and provenance

- **Confirmed (source):** a literal value, branch, or relationship in the inspected
  artifact. This establishes app behavior as written, not successful device behavior.
- **Confirmed (device):** a result observed on our Select; not transferable to another model.
- **Probable:** a supported interpretation whose expansion or intent is not explicit.
- **Unknown:** no reliable expansion, meaning, or runtime validation yet.
- **Standard:** established terminology; context still matters.

The main artifact is Android `com.hp.impulse.sprocket` **3.0.2921.1**, version code
**74251**, base APK SHA-256
`6395bd47fa7c669dd5fbc4a5408a4d54dd8c1841e8581be898f3bf90caaa405c`.
See [NEWER_APK.md](NEWER_APK.md) for acquisition and comparison details.
Local source references below are relative to
`logs/current-decompiled/sources/`; these vendor files are intentionally ignored
and are not distributed with this repository. JADX output has reconstruction
limitations and the whole-app decompilation reported errors; runtime behavior is
not implied by an enum entry. Facts are summarized here without copying vendor code.

Historical iOS evidence comes from the 2017 MobilePrintSDK snapshot identified in
[IOS_EXPLORATION.md](IOS_EXPLORATION.md), under local `logs/historical-ios/`.
The acquired current iOS executable is encrypted; declarations from it do not
establish equivalent implementations or resolve missing acronym expansions.

## There is more than one naming scheme

Several product codenames are island/place names: Maui, Bahama, Grand Bahama,
Ibiza, Malta, and Luzon. The mappings below are explicit in the app; the reason
HP chose each place is unknown. Geographic names do not imply protocol compatibility.
Impulse, Manta, Matterhorn, numeric HP model identifiers, and protocol abbreviations
belong to other naming schemes. There is no demonstrated single acronym rule.

| Name | Resolved role or mapping | Evidence / uncertainty |
| --- | --- | --- |
| `IMPULSE`, `impulselib` | Original HP sprocket profile; namespace of the multi-model Android library | Confirmed source. No acronym expansion found; namespace persists beyond that model. |
| `MAUI` | HP sprocket 2-in-1 | Confirmed source; Maui is a Hawaiian island. Uses a dedicated Maui client. |
| `BAHAMA` | HP sprocket plus / Bluetooth alias `HP sprocket+` | Confirmed source. Distinct from Select despite shared image dimensions. |
| `GRAND_BAHAMA` | HP Sprocket Select | Confirmed source and our device context. Grand Bahama is an island name; do not interpret “Grand” as a protocol version. |
| `IBIZA` | HP Sprocket 200 family | Confirmed source. Bluetooth names containing `HPMalta-` also map here; why Malta and Ibiza coexist is unknown. |
| `LUZON` | HP Sprocket Studio; also name pattern `HPLuzon-` | Confirmed source; Luzon is a Philippine island. Extends HPLPPDevice rather than HPLPPZinkDevice. |
| `Manta` | Historical iOS printer implementation | Confirmed historical class name; exact cross-platform alias and naming rationale remain unproven here. |
| `Matterhorn` | Native library loaded by Android PhotoFix | Confirmed role; mountain name, with naming rationale unknown. |
| `HP200`, `HP200D`, `HP400`, `HP500`, `HP600` | Additional numbered app profiles | Confirmed identifiers, not universal aliases across all code generations. `D` has no confirmed expansion. |
| `CLASSIC` | Separate app profile, fallback name HP Sprocket 200 | Confirmed enum and SprocketClassicDevice use. Do not equate this label with every Bluetooth Classic transport. |
| `NONE` | Unresolved/default enum profile | Not a printer family and not evidence that an unidentified device is supported. |

Primary source locations: `com/hp/impulselib/device/SprocketDeviceType.java`,
individual `*Device.java` files in that directory, and
`com/hp/impulse/sprocket/classic/SprocketClassicDevice.java`.

## Acronym glossary and confidence

| Token | Meaning / role | Confidence and limits |
| --- | --- | --- |
| HP | Hewlett-Packard brand origin | Standard brand meaning; does not decode the rest of a firmware identifier. |
| HPLPP | Internal printer protocol/library namespace | Role confirmed; **full expansion unknown**. “Low Level” and “Lightweight” are guesses, not documented expansions. |
| `HP+` | Literal protocol frame signature | Confirmed wire marker; not evidence of a relationship to the HP+ commercial service. |
| TMD | Separate historical data/update class and version field | Role confirmed; **expansion unknown**. Historical iOS has `SprocketDataClassTMD = 1` and `tmd_version`; image is class 0 and firmware class 2. This does not prove its contents or safety. |
| RLT | Probably Real Life Technologies | Strong inference: PhotoFix uses `rlt_jni_small`, and HP documents Photo Fix using Real Life technologies. The APK does not spell out RLT. |
| JNI | Java Native Interface | Standard; the bridge between Java and native image processing here. |
| ORB | Oriented FAST and Rotated BRIEF | Standard computer-vision algorithm. |
| HPORB | Probably HP's ORB-based vision implementation | Native train/track/detectAndCompute symbols support this inference. The vendor's formal expansion is not recovered; not a printer transport acronym. |
| ZINK | Zero Ink | Standard technology/brand expansion; shared media technology does not imply a shared command protocol. |
| BT / BLE | Bluetooth / Bluetooth Low Energy | Standard. Classic and BLE are different transport paths. |
| GATT / ATT | Generic Attribute Profile / Attribute Protocol | Standard Bluetooth terms. `SYS_ATT` in printer commands instead denotes system attributes. |
| SPP / OPP / OBEX | Serial Port Profile / Object Push Profile / Object Exchange | Standard; useful for understanding the older Impulse/Bahama control and image routes. |
| RFCOMM | Bluetooth serial-port emulation protocol | Established protocol name; no additional vendor expansion inferred. |
| SDP / UUID | Service Discovery Protocol / Universally Unique Identifier | Standard Bluetooth/service identification terminology. |
| FW / SW / HW | Firmware / software / hardware | Conventional and consistent with version/property use. |
| REQ / RSP / EVT | Request / response / event | Source naming conventions. An event name alone does not decode its payload. |
| RD / WR / CFG / SYS / IF | Read / write / configuration / system / interface | Source naming conventions; inspect the containing enum for numeric values. |
| SEC / AUTH | Security / authentication | Conventional roles; actual security-mode semantics remain unknown. |
| TX / RX / ACK | Transmit / receive / acknowledgement | Standard transport terminology. |
| TLV / LE / BE | Tag-length-value / little-endian / big-endian | Encoding terminology. `LE` in an integer description is not “Low Energy.” |
| RGB / UI / UX | Red-green-blue / user interface / user experience | Standard. Firmware LED RGB and displayed UI color can intentionally differ. |
| DPI / PPI | Dots per inch / pixels per inch | Distinct physical-output and image-sampling concepts; input dimensions do not establish print-head resolution. |
| APK / IPA / SDK | Android application package / iOS app archive / software development kit | Artifact categories. An internal SDK compiled into DEX is not necessarily a separately reusable JAR/AAR. |

External primary references: [HP Real Life technologies](https://www.hp.com/hpinfo/abouthp/iplicensing/technology/consumer.html),
[HP A640 guide, Photo Fix](https://h10032.www1.hp.com/ctg/Manual/c01846782.pdf),
[OpenCV ORB](https://docs.opencv.org/4.13.0/d1/d89/tutorial_py_orb.html),
[Oracle JNI](https://docs.oracle.com/en/java/javase/21/docs/specs/jni/intro.html),
and [Bluetooth GATT specification](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Core-60/out/en/host/generic-attribute-profile--gatt-.html).
The older HP manual supports the RLT interpretation, not a claim that the Select
implements every enhancement listed for that older printer.

Local evidence: `com/hp/photofix/PhotoFix.java`, ignored
`logs/android-native/libhporb.strings.txt`, and historical
`Pods/MobilePrintSDK/Pod/Classes/Private/MPBTSprocketDefinitions.h`,
`Manta/MPBTManta.m`, and `Maui/MPBTMaui.m`.

## Firmware and routing names

For our observed Select firmware **G1L1FA2105AR**:

| Portion | What the app actually establishes | What remains unknown |
| --- | --- | --- |
| Entire string | HPLPP resolver expects 12 characters | Whether all supported firmware generations follow it |
| `G1L1FA` (first six) | Select firmware lookup key becomes `GrandBahama-G1L1FA` | Expansion of G1, L1, FA and whether they encode hardware, platform, or build family |
| `2105` (positions 6–9, zero-based) | Parsed as an integer for validation | Whether this is a date, sequence, or another identifier; no year/week interpretation established |
| `2105A` (positions 6–10) | Compared lexicographically when deciding whether a candidate is newer | Semantic meaning of A |
| `R` (position 11) | If the preceding comparison is equal, a lower character is considered newer | Semantic meaning of R and rationale for reverse ordering |

This describes `bt/hplpp/HPLPPFirmwareUpdateResolver.java`, not a recommendation
to alter firmware strings or perform updates. Case-insensitive full equality is
handled before comparison; only the DEFAULT update type is applicable there.

Firmware key prefixes in the device classes include `HP` (Impulse), `Maui`,
`BAHAMA`, `Ibiza-`, `GrandBahama-`, `Luzon-`, `HP200-`, `HP200D-`, and `HP400-`.
The HPLPP classes generally append the first six software-version characters.
HP200Device chooses the HP200D prefix when the software version starts with
`M2L2FS`; preserve that branch
rather than assuming the class name alone fixes the firmware target.

MauiDevice also contains `HP500-P1L1FS-TMD`, while the current enum calls HP500
“Sprocket Panorama.” This collision is a reason to retain namespace, artifact
version, and call-site context. It does **not** prove Maui and Panorama are the
same device. P1/L1/FS and the suffix TMD are not fully decoded.

## Fully resolved app profiles

Values below come from the current APK's `SprocketDeviceType` enum. Width × height
is the enum's image profile in pixels; paper text is the literal app label in
inches. These are **not measured physical resolutions, firmware acceptance limits,
or proof that every active print path uses this enum**. Flags are enum declarations,
not evidence of a tested transport on each device.

| Enum | Name fallback | Image profile | Paper label | JPEG quality | HPLPP / prefer BLE |
| --- | --- | --- | --- | --- | --- |
| IMPULSE | HP sprocket | 640 × 1002 | 2 x 3 | 90 | false / false |
| MAUI | HP sprocket2-in-1 | 640 × 1002 | 2 x 3 | 90 | false / false |
| BAHAMA | HP sprocket plus | 768 × 1152 | 2.3 x 3.4 | 90 | false / false |
| IBIZA | HP Sprocket 200 | 640 × 1002 | 2 x 3 | 90 | true / true |
| CLASSIC | HP Sprocket 200 | 640 × 1002 | 2 x 3 | 90 | false / false |
| HP200 | HP Sprocket 200 | 640 × 1002 | 2 x 3 | 90 | true / true |
| HP200D | HP Sprocket 200D | 640 × 1002 | 2 x 3 | 90 | true / true |
| HP400 | HP Sprocket 400 | 793 × 972 | 3 x 4 | 90 | true / true |
| HP500 | HP Sprocket Panorama | 800 × 1100 (initializer) | 2 x 9 | 90 | true / true |
| HP600 | HP Sprocket 600 | 1232 × 1786 | 3 x 4 | 90 | true / true |
| GRAND_BAHAMA | HP Sprocket Select | 768 × 1152 | 2.3 x 3.4 | 90 | true / true |
| LUZON | HP Sprocket Studio | 1224 × 1836 | 4 x 6 | 70 | true / true |

NONE carries 640 × 1002, “HP sprocket,” 2 x 3, quality 90, false/false as defaults.
Do not treat these as capabilities of an unidentified device.

Resolved aliases:

- `Imgcodecs.IMWRITE_JPEGXL_QUALITY` = **640**. JADX reused a matching numeric
  constant name. This is not evidence of JPEG XL output. The inspected enum gives
  **640 × 1002**, not the sometimes cited 668 × 1002; the difference needs separate
  version/call-path investigation before changing any print implementation.
- `ImageUtil.PHOTOBOOTH_WIDTH/HEIGHT` = **1224 / 1836**.
- `AppUtil.PAPER_SIZE_WIDTH/HEIGHT` initialize to **800 / 1100**. They are mutable
  static fields, unlike the other constants. No further assignments were found
  in the recovered HP Java sources; runtime/native/reflection effects are untested.
- `ViewCompat.MEASURED_SIZE_MASK` = **16777215 = 0xFFFFFF**, used for a color value.
  It does not mean printer colors depend on Android view sizing.

HP500's geometry does not match its paper-label aspect ratio; HP600 also contains
`PRT-`, `LP-`, and `HP Sprocket Studio Plus` prefix constants while its fallback
is “HP Sprocket 600.” These are **source inconsistencies/alias clues requiring
call-path tracing**, not grounds to rewrite values to plausible marketing sizes.

For Select specifically, preprocessing obtains the enum print size, 768 × 1152.
Inherited `HPLPPDevice.getImageDimensions()` returning null is a different method.
BahamaDevice.getImageDimensions() directly returns its enum's 768 × 1152.
Neither establishes arbitrary-size JPEG acceptance or native dot placement.

## Candidates for future support

No new device is enabled by this document. Keep model verification and per-model
request allowlists; do not broaden Select's guard based only on a similar name.

| Candidate | Evidence for reuse | Missing work before claiming support |
| --- | --- | --- |
| Sprocket 200 / Ibiza | HPLPPZinkDevice inheritance; independent openZinkBooth protocol and printing research | Obtain exact unit/firmware identity, capability table, transport/ACK behavior, and read-only traces. Resolve IBIZA vs HP200 vs CLASSIC routing and 640/668 geometry discrepancy. |
| HP200D | HPLPPZinkDevice class and firmware key | Establish retail identity and meaning of D; verify actual features and reads on hardware. |
| HP400 | HPLPPZinkDevice class and distinct image profile | Verify product identity, transport, media and capability differences; do not assume Select dimensions/status semantics. |
| Original Sprocket / Impulse | Older command implementations and historical iOS comparison | Separate protocol backend. Impulse/Bahama control uses SPP with older 1B 2A framing, with OPP image transfer; not drop-in HPLPP. |
| Sprocket Plus / Bahama | Explicit mapping, BahamaClient derived from ImpulseClient | Separate older-protocol backend and physical read validation. Matching Select image size does not imply matching wire format. |
| Sprocket 2-in-1 / Maui | Dedicated MauiClient and historical Maui implementation | Map camera/printer-specific fields and update classes; physically validate read-only operations. |
| Sprocket Studio / Luzon | HPLPPDevice inheritance and model feature table | Audit non-ZINK assumptions, supply/status fields, transport and image processing; physical reads required. |
| Panorama / HP500 | Enum and separate firmware/configuration references | Trace actual routing and render pipeline before choosing a backend. Enum HPLPP flag alone is insufficient; resolve unusual dimensions. |
| HP600 / Studio Plus naming clues | Enum and prefix constants | Confirm identity mapping, actual transport/client and media profile; source labels conflict. |
| Canon IVY 2 | Separate ivy2-sprocket2 reference implementation | Treat as another backend until protocol equivalence is demonstrated. Reference README reports Raspberry Pi 3b+ testing; that is not our macOS/device validation. |
| Xiaomi Mi Portable | Separate mi-portable-photo-printer implementation; model XMKDDYJ01HM / MIoT hannto.printer.basil | Distinct authentication/encryption/protocol work, not an HPLPP alias. Reference project claims macOS support and 1040 × 1560 input; independently validate before adoption. |

Reference snapshots: openZinkBooth `8e1df0b`, its wiki `c864f81`,
ivy2-sprocket2 `b56cbfc`, mi-portable-photo-printer `85335b6`. These are independent
research sources, not vendored implementations or guarantees of compatibility.

A practical order is Sprocket 200 read-only support first, then verified HPLPP
ZINK variants, then separate older-protocol or other-vendor backends according
to hardware availability. PAPPL remains a later integration target. Printing,
firmware updates, calibration feeds, and potentially auto-printing image uploads
require their own explicitly authorized milestone; none were performed here.

## Open research questions

1. Find an explicit vendor expansion of HPLPP and TMD, or leave them unexpanded.
2. Explain Malta/Ibiza coexistence and map numbered profiles to actual identifiers.
3. Trace HP500/HP600 through selection, connection, preprocessing, and transmission.
4. Verify the 640 × 1002 profile against DEX instructions and actual selected runtime
   paths; compare historical 668 × 1002 claims without treating either as native DPI.
5. Determine firmware-prefix/suffix semantics from multiple known releases or vendor
   documentation; comparison logic alone cannot explain the naming rationale.
6. Resolve unknown Select event/security fields independently of their suggestive names.
