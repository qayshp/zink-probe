# Select-family color tables and diagnostic paths

2026-10-22. Offline follow-up to the question whether CAL-03's requested RGB
cyan, magenta and yellow isolate physical dye layers.

**2026-10-23 follow-up:** [LUT execution and factory-path tracing](FIRMWARE_LUT_TRACE.md)
resolves temperature selection, RGB interpolation and the fourth byte's MDX role.
It also finds that the QA pattern entries below are placeholders and that the
factory JPEG path clears counters. A matched FA/FS pair from another family
narrows the naming difference to distinct software builds with a debug-policy
difference, while exact Select FA equivalence remains unverified.

**Found:** populated color/tone/thermal resources and executable factory/test
branches in downloadable Grand Bahama firmware. **Not established:** an RGB
triplet that isolates one physical dye layer, a complete RGB-to-heat model, or a
safe, supported command for a built-in single-dye test page on the tested Select.

No printer connection, setting change, firmware update, diagnostic invocation,
new chart render or print was performed. CAL-03 remains prepared and unprinted.
Firmware and extracted vendor code remain in ignored local `logs/`; the repository
contains an independent inspector, hashes, numeric summaries and research notes.

## Provenance and the FS/FA boundary

The inspected Android APK is Sprocket **3.0.2921.1**, versionCode **74251**,
SHA-256 `6395bd47fa7c669dd5fbc4a5408a4d54dd8c1841e8581be898f3bf90caaa405c`.
See [NEWER_APK.md](NEWER_APK.md) for acquisition/signature provenance.
Its `com.hp.impulse.sprocket.util.WebFirmwareUtil.FirmwareServerUrl`
points all four environments at this public
[firmware catalog](https://d1te6mvvpy6zcm.cloudfront.net/firmwares/fw_release.json).
The classic firmware service uses the same host/catalog path.

The fetched catalog SHA-256 is
`f495eddc16aaff7c42bb6a09d1522971e2b7bd8b72da78cdc51a2883241fb649`.
Its `GrandBahama-G1L1FS` key lists these packages; each downloaded file matches
the catalog's MD5. This is download-integrity evidence, not signature validation.

| Firmware | Catalog date | Catalog latest | File bytes | SHA-256 |
| --- | --- | --- | ---: | --- |
| G1L1FS1941AR | 10-29-2019 | false | 1,905,504 | `74f9e9e42cdc0f646fb54b24fe93f9194bb7731763a786fbf16f9f92f582d9b8` |
| G1L1FS2050AR | 12-28-2020 | false | 1,942,916 | `9a66701726c4628470372fa2235e1f54a1ec699ad021245a32f995cb3ad54290` |
| G1L1FS2105AR | 03-04-2022 | false | 1,942,964 | `68cc7a635342e1e882b1e552c9d1ee2803b1c5928d61a0612f69e689d9f08a60` |
| G1L1FS2210AR | 08-10-2026 | true | 1,947,532 | `da1d309df19beb0ed551577de0e2934a9c5235719382a37a5aefb41c8dc50bd8` |

Exact URLs, MD5s and acquisition metadata are in
[provenance.json](experiments/firmware/provenance.json).
The catalog date is reproduced literally; it does not establish a build date.

**Our physically tested printer reports `G1L1FA2105AR`, not `G1L1FS2105AR`.**
The catalog has no `GrandBahama-G1L1FA` key. The APK's
`com.hp.impulselib.device.GrandBahamaDevice.resolveFirmwareKey()` constructs
`"GrandBahama-" + softwareVersion.substring(0, 6)`; it does not normalize FA to FS.
The downloaded program also contains FS version strings. We have not resolved
the suffix distinction or acquired an exact FA image. These are related-family
findings, not proof of identical code/tables in the physical printer or compatible
update packages. No update recommendation follows from this investigation.

## Container and reproducibility

All four files contain an `OART` directory at file offset `0x100000`:
40-byte header, 23 twelve-byte `<address, length, flags>` entries, and a named
string table. The observed resource address base is `0x80000000`.
The `FIRMWARE` region starts at file offset `0x1001fc` and contains gzip-compressed
ARM32 little-endian code/data. Decompression completed with gzip integrity checks.
The 2105 main image is 1,385,728 bytes, SHA-256
`4cc83261d16ab8078db3a38ae694017c26e6c681e1eca1e9bb41a437704c24ce`.

The independent [inspector](experiments/firmware/inspect_rbn.py) reads local files
and produces [reports.json](experiments/firmware/reports.json). It has no network
or printer access. It checks region bounds and caps decompression at 16 MiB.
It does not validate vendor signatures or implement a firmware updater.

```sh
python3 -m unittest discover -s experiments/firmware -v
python3 experiments/firmware/inspect_rbn.py logs/color-firmware-research/*.rbn \
  > experiments/firmware/reports.json
```

Seven synthetic boundary/decompression tests pass. All four actual packages were
parsed. The inspector's known resource layouts apply to these observed images;
it is not a universal firmware parser. Manual ARM analysis used Capstone 5.0.9 in
an isolated research environment. Whole-image disassembly includes data mistaken
for instructions; the findings below use specific control-flow/constant-load
sequences, not arbitrary disassembly labels.

## Actual color-processing resources

Offsets in this table are in the RBN container. The reports include full hashes.

| Region | File offset | Allocated size | Established content / limits |
| --- | ---: | ---: | --- |
| `STREAK_CORRECTION` | `0xa0000` | 8,192 | Named populated correction region; detailed layout not decoded. |
| `TONESCALE`, `TONESCALEb` | `0xa2000`, `0xa3000` | 4,096 each | Identical; 256 triplets of little-endian floats followed by `ff` padding. |
| `TMD_REPLACE` | `0xb0000` | 131,072 | Named replacement/calibration resource; not a demonstrated dye-isolation command. |
| `MMT`, `MMT2` | `0xd0000`, `0xd4000` | 16,384 each | Identical within each package; float data used in tone/gamma preparation. Full acronym/format remains unresolved. |
| `LUT1_Z21` through `LUT6_Z21` | `0xd8000` through `0xf1000`, step `0x5000` | 20,480 each | Six distinct populated color maps, each with 4,913 four-byte records then `ff` padding. |
| `ZINK_THC` | `0xf6000` | 40,960 | `zTHC`, layout version 2; numeric thermal/geometry parameters used by the program. |

The entire tone array fits the triplet formula
`((255-i)/100, (255-i)/100, (255-i)/100)`, `i=0..255`, to float32 precision
(maximum absolute error `1.15e-7`). This describes the stored data; the values
are not established dye densities or pulse durations.

The LUT record count is exactly **17 cubed**. More than size matching supports
this: in the 2105 main image, the adjustment routine at `0x2ba68` reads/writes
the first three bytes, skips the fourth, and loops **0x1331 = 4,913** times
(`0x2bc78–0x2bca0`; literal at `0x2bd20`). The follow-up establishes RGB-axis
order, temperature selection, trilinear interpolation, and a fourth-byte index
into a magenta duty/divider table; see [the execution comparison](FIRMWARE_LUT_TRACE.md).

The loader at `0x2bd3c` looks up all six named LUT resources. It optionally applies
three-component adjustments at six color-cube corners, with code/logging that
identifies color-map and dR/dG/dB adjustments. Its copy-size ceiling is
**0x4de0 = 19,936 bytes**, not 4,913 times four. The first 19,652 bytes are the
records processed by the loop; the difference is padding in these files.

As a small example of differing raw maps, the four-byte record at array index
4,640 is `[255,0,255,18]` in LUT1 and `[255,191,255,16]` in LUT5. This is an
array observation, **not a statement that input magenta becomes those dye
amounts**. Raw corner records are recorded with numeric indices in the JSON to
avoid assuming input-axis or output-channel semantics.

All six LUT regions, both tone-scale regions, streak correction, and TMD replacement
are byte-identical across 1941/2050/2105/2210. MMT/MMT2 and ZINK_THC match within
1941/2050 and within 2105/2210, but differ between those pairs. Thus copying only
the six color maps would omit other changing parts of the imaging pipeline.

### Thermal fields and the resolution question

These values are present in all four packages. Offsets below are relative to the
`ZINK_THC` resource, not the whole file.

| Offset / type | Stored value | Evidence / interpretation |
| --- | --- | --- |
| `+0x110`, float32 | approximately 0.0477051884 | Energy-scaling calculation uses it; exact units not established. |
| `+0x114`, float32 | approximately 0.235 | Passed to a diagnostic format labeled `W`; not established total printer wattage. |
| `+0x118`, float32 | approximately 0.100 | Passed to a diagnostic format labeled `ips`: nominal 2.54 mm/s parameter, not a measured paper-feed speed. |
| `+0x11c`, uint16 | **321** | Passed to the `DPI` field of a diagnostic message. |
| `+0x11e`, uint16 | **600** | Passed to the `LPI` field of the same message. |
| `+0x128`, text | `15-Jan-2021 16:07:51` in 2105/2210 | Embedded thermal-data timestamp; older pair says `10-May-2019 13:37:41`. |

In 2105, `0x2d3f8–0x2d488` loads the thermal parameters and performs calculations;
`0x2d474–0x2d488` loads the two uint16 fields and passes them to the DPI/LPI log.
The relevant formats are at `0x2d704` (leading space before `zTHC`) and `0x2d71c`
in the decompressed file.
This is more direct evidence of the firmware's configured spatial parameters
than a marketing specification. It still does not count physical heaters, prove
the current FA unit uses identical data, or make the 768×1152 input JPEG a
one-input-pixel-per-heater/line interface.

The program also has code/logging for temperature, preheat/overheat, adaptive cyan
and cooling. Detailed equations and active paths have not been fully reconstructed.

## Diagnostic and factory modes: what was actually found

### APK

The inspected Select HPLPP trigger enumeration names only resume-print (1) and
reboot (2); the prior physical capability response advertised trigger ID 2.
This is not evidence that no hidden firmware path exists.

Other leads do not establish a working Select test-page command:

- `DPL_DIAGNOSTICS` is a false-by-default feature entry; no other reference was
  found in the recovered Java. A generic diagnostics dialog is not a printer mode.
- Calibration analytics count card passes. Select print-quality screens explain
  the supplied colored card. Other calibration/cutter strings belong to different
  device families or unreferenced resources.
- HPLPP `JOB_COLOR` is job metadata, not an exposed printer color-conversion table.
- The Android JPEG's sRGB ICC data is not a Select output profile.

Searches covered recovered HP Java/resources and native-library string triage;
this was not exhaustive decompilation of every native function. No app-embedded
Select LUT file, single-dye command, or verified test-page button was recovered.

### Firmware

The 2105 program contains an executed QA help-menu routine at `0xb670–0xb6dc`
whose entries include TPH test, test-pattern selection and continuous-print
selection. Source-path strings associate it with `ds_QaTest.c`.
**Follow-up correction:** tracing the dispatcher shows pattern/continuous-print
entries are no-ops and TPH/Bluetooth/USB/battery entries only log messages in
this build. Some other entries change state, including NVRAM defaults. The menu
does not establish a working pattern generator or accessibility through the
normal app protocol. See [the traced entry table](FIRMWARE_LUT_TRACE.md#4-factory-patterns-and-mcal-findings-versus-misleading-leads).

An engine-test path offers **MCal mode**. Its wrapper at `0x1bcf4` calls
`0x30adc`, which changes state used in tone/TMD setup. The precise expansion of
MCal, semantics of each mode, and host transport remain unresolved. Another
tempting entry, “Zink Test du jour,” calls `0x309e8`, associated with a barcode
test; it should not be described as a pure-color calibration page.

There is also a **special factory marker in the JPEG handler**. At `0x8e84`,
the incoming-buffer path copies nine bytes beginning at offset 6 and compares
them with the NUL-terminated marker `JFIFFINIT`. Equality selects a branch
logged as `__FACTORY_MODE__`, calls `0xd868`, changes state, and continues into
the image handling path. The normal branch is separately logged. This marker
also occurs in the 2210 image. It was not found in the recovered HP Java.

The follow-up establishes that this branch zeros 16 counter-store entries and a
configuration field. Persistence and all field meanings remain incompletely traced.
No specially marked JPEG was constructed or transmitted. It is not yet a
confirmed maintenance interface, a safe read-only switch, or a pure-dye bypass.
Likewise, “Enable USB Debuging” and debug-task strings are leads; we have not
established a reachable USB/UART console on this printer.

Addresses here refer to the decompressed 2105 file. The follow-up resolves the
startup scatter layout: the traced code uses runtime address = file offset minus
`0xc0`, while data sections have their own mappings. It uses those mappings for
absolute-pointer analysis and isolated execution.

## What kind of calibration page would answer the question?

Three distinct experiments should not be conflated:

1. **The supplied orange card:** an input to the printer's paper setup/cleaning
   workflow. The official [Select manual](https://cdn.shopify.com/s/files/1/0459/7625/6672/files/HP_Sprocket_Select_2.3x3.4_Product_Manual_ENGLISH.pdf)
   describes a card specific to the paper pack. It is not a page we ask the printer
   to generate, and its use does not demonstrate that RGB cyan means cyan-only heat.
2. **A normal RGB characterization chart:** CAL-03 can compare the end-to-end
   response to different requested colors and geometry. A larger patch chart with
   instrument measurements could support empirical color correction. Neither
   experiment alone reveals which dye layers were energized; a photograph of
   nominal CMY is insufficient to infer that internal separation.
3. **A factory/raw-channel test pattern:** potentially much more direct, if its
   generator and bypass path can be shown to drive known channels/energies.
   The firmware now provides leads for this, but we have not established an
   accessible page with that property. A pattern merely labeled “test” is not enough.

The official [print-quality procedure](https://sprocketprinters.com/pages/select-photo-printer-using-quality)
describes the colored card and ordinary image adjustments; no individual-dye
diagnostic selector was identified in the reviewed documentation. Some documented
card workflows involve sending a print job, so none was attempted here.

## Consequence for CAL-03 and the driver

The qualification on CAL-03 stands: **matched requested-color controls, not
verified isolated dye layers**. The new evidence explains why that distinction
matters: the stored maps are only part of a configurable, calibration-dependent
pipeline before thermal control.

The [subsequent trace](FIRMWARE_LUT_TRACE.md) completes the initial LUT arithmetic
and fourth-byte investigation, narrows MCal bypasses, and rejects the QA-menu
entries as evidence of a generator. An exact Select FA image and the remaining
tone/thermal stages are still needed for a complete model; no channel-isolating
stimulus or safe factory page has been established.

For the ordinary Mac/Linux/Windows driver, continue sending the known JPEG input
and let firmware perform its own color and thermal processing. Reapplying its
internal LUTs on the host could double-correct the image. This research does not
block the [portable job-engine milestone](DRIVER_ROADMAP.md), and does not justify
changing the standard input dimensions or adding a fixed thermal correction.
