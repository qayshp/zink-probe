# Temperature LUTs, factory paths, and FA/FS evidence

2026-10-23. Follow-up to [the initial resource investigation](FIRMWARE_COLOR_DIAGNOSTICS.md).

**Established for the downloaded G1L1FS2105AR build:** six temperature-indexed
maps, their blending arithmetic, RGB-axis order, trilinear pixel interpolation,
and a fourth component that selects a magenta duty/divider pair. A Python
reference matches isolated execution of the actual ARM routines.

**The factory-pattern lead did not yield a generator.** The QA menu's pattern
and continuous-print entries are no-ops in this build. The special factory JPEG
path clears counter state. MCal can bypass some processing, but is not a verified
single-dye page or a supported app command.

**FA/FS is narrowed, not fully decoded.** A matched HP500 FA/FS pair has identical
non-program resources and a concrete debug-monitor policy difference. The Select
FS code has a similar check. We still lack the Select's exact FA image and the
authoritative expansion of the letters.

Everything here was offline: no printer connection, debug activation, setting
change, firmware update, marked JPEG transmission, or print. CAL-03 is unchanged
and unprinted. Vendor binaries and extracted tables stay in ignored local logs.

## Evidence and execution boundary

The principal package is `G1L1FS2105AR_1.0.7.rbn`, SHA-256
`68cc7a635342e1e882b1e552c9d1ee2803b1c5928d61a0612f69e689d9f08a60`;
its inflated main image is
`4cc83261d16ab8078db3a38ae694017c26e6c681e1eca1e9bb41a437704c24ce`.
The physically tested Select reported **G1L1FA2105AR**. Findings about this
downloaded FS program are not a verified description of every instruction/table
in that FA unit. Acquisition provenance is in the preceding report.

Unless explicitly called a RAM address, addresses below are **offsets in the
inflated FS2105 file**. Its startup scatter table at `0x1b0..0x280` describes 13
copy/zero operations. In the code ranges traced here, runtime instruction
address = file offset minus `0xc0`. Some initialized data has a different mapping;
the `0x40000000` bit denotes an alias normalized to physical RAM in the emulator.
The previous investigation's file-offset labels remain valid, but interpreting
absolute pointers requires these mappings.

[trace_lut.py](experiments/firmware/trace_lut.py) loads that scatter layout into
Unicorn 2.1.4, enables ARM VFP, and executes only the selected arithmetic/lookup
routines. It supplies the six unadjusted shipped maps, the traced knot records,
buffer pointers, normal mode zero, and synthetic temperature state. Temperature
retrieval and three service/log/wait callees are stubbed. Peripheral addresses
are not mapped; execution outside the listed function ranges fails; each call
has instruction and time limits. Input hashes are required before execution.

This does **not** run boot, the optional per-unit color-map adjustments, media
calibration, JPEG decoding, the complete thermal pipeline, or the firmware's
real sensor loop. It is an arithmetic equivalence experiment.

## 1. What selects a LUT?

At `0x2d87c..0x2d934`, resource initialization associates `LUT1_Z21` through
`LUT6_Z21` with knots **20, 30, 40, 50, 60, 70**, each spaced by 10. The records
are 12 bytes each at RAM `0x15786c`: map pointer, float knot, float interval.
The temperature comes from the thermal state's derived/filtered estimate at RAM
`0x157804+4`, not a directly supplied room-temperature reading. The surrounding
thermal logic combines head/mechanism temperature state and offsets; the complete
estimate has not been independently reconstructed.

The initial selector (`0x2a68c..0x2a77c`) does the following:

1. Obtain the temperature estimate, perform service/wait operations, obtain it
   again, and subtract **0.5**.
2. Clamp that effective value to **20..70**.
3. Select the adjacent pair bounding it. The upper endpoint uses pair 60/70.
4. Build a signed-byte difference array between the two maps and blend them with
   an integer weight from **0 through 256**.
5. Validate that all six maps' fourth components are no greater than **36**.

For a synthetic getter value of 35, the effective temperature is 34.5. The
selected pair is LUT2/LUT3 (30/40); weight is 115/256 and the recorded quantized
temperature is **34.4921875**. The quantization step is **10/256 = 0.0390625**.

For lower knot `L` and effective temperature `T`, the weight is:

```text
q = truncate_toward_zero(float32(T - L) * float64(25.6))
```

The difference builder at `0x2a59c` stores each `next-current` difference in a
byte. The blend routine at `0x2a4a0` reads it as signed. All adjacent differences
in the supplied maps fit signed-byte range (observed overall range **-91..96**).
For each record, the first three lanes are:

```text
base + truncate_toward_zero(delta * q / 256)
```

The fourth lane uses:

```text
base + truncate_toward_zero((delta * q + 128) / 256)
```

That positive rounding bias matters for negative deltas too; it is not ordinary
round-to-nearest applied symmetrically. The reference preserves the actual byte
storage and signed rounding behavior.

The later update path at `0x31dcc..0x31e44` can advance the interval as the derived
temperature rises and reblend after sufficient change. It does not implement a
fresh symmetric low/high search like the initial selector. Only initial selection
and blending were execution-validated here; a full heating/cooling session and
its callers are outside this experiment.

## 2. How an RGB pixel is looked up

The routine at `0x2a780..0x2aba4` takes three planar RGB buffers plus a pixel count,
updates the three components in place, and writes a separate fourth-component
plane. Its table index is:

```text
((R >> 4) * 289 + (G >> 4) * 17 + (B >> 4)) * 4
```

Thus **R is the slowest axis, G the middle, B the fastest**. It uses the low four
bits of each input component as fractions, combines the eight neighboring cube
vertices with **trilinear interpolation**, and divides the accumulated products
by 4096 using a right shift. All four components use this interpolation.

The grid is effectively 0,16,...,256: input 255 lies 15/16 through the final cell.
It does not directly select the terminal node. This explains why a raw corner
record and the output for an 8-bit RGB corner can differ by a few units.

Examples from isolated execution, with optional per-unit adjustments absent:

| Requested RGB | LUT1 / effective 20: intermediate RGB; MDX | Effective 50: intermediate RGB; MDX |
| --- | --- | --- |
| Black `(0,0,0)` | `(0,0,0); 30` | `(0,0,0); 30` |
| White `(255,255,255)` | `(253,254,254); 29` | `(253,254,254); 29` |
| Cyan `(0,255,255)` | `(11,255,254); 20` | `(0,254,254); 20` |
| Magenta `(255,0,255)` | `(254,0,254); 18` | `(254,99,254); 17` |
| Yellow `(255,255,0)` | `(254,253,23); 17` | `(254,253,0); 17` |
| Gray `(128,128,128)` | `(138,140,154); 18` | `(137,145,154); 18` |

These are **intermediate code values**, not measured ink/dye quantities, heater
energies, or a prediction of printed appearance. In particular, the magenta
example changes both an intermediate RGB component and the MDX setting. It is
not legitimate to inspect the RGB triplet alone and conclude how much physical
magenta is activated.

## 3. The fourth byte: MDX duty/divider index

The fourth component is an **index into a magenta control table**. This establishes
its role without establishing the expansion of the acronym MDX.

- `0x31cec..0x31d6c` checks indices 0..36 in the six maps.
- `0x2cf9c..0x2cff8` builds the 37-entry duty/divider lookup at RAM `0x157810`.
- Its getter at `0x36c94` reads bytes 6/7 of eight-byte records at RAM `0x14e2f0`.
- `0x2ae04..0x2aebc` uses the interpolated index, multiplies a magenta-related
  intermediate quantity by duty, divides by 1/2/3/4, and bounds it against another
  quantity. Diagnostic branches explicitly name `mdx duty`, `mdx divider`, and
  `mag`.

All 37 getter outputs were execution-checked. Examples: index 0 → `(4,1)`,
12 → `(6,1)`, 16 → `(20,3)`, 17 → `(27,4)`, 18 → `(7,1)`, 30 → `(9,1)`,
36 → `(10,1)`. Some neighboring indices share a pair. The complete small numeric
list is in [lut-trace-results.json](experiments/firmware/lut-trace-results.json).

This is a control index, not alpha, not an independent fourth ink channel, and not
a direct percentage. The later scheduling/energy operations still matter.

## 4. Factory patterns and MCal: findings versus misleading leads

| Lead | Traced behavior in FS2105 | Conclusion |
| --- | --- | --- |
| QA `[11] Test Pattern Type Set` | Jump-table entry at `0xdac0` goes directly to command-byte clear at `0xdbf8` | No pattern selected/generated by this entry |
| QA `[12]` continuous-print selection | Entry at `0xdac4` takes the same cleanup path | No continuous-print implementation in this entry |
| QA `[8]` TPH test | `0xdb28` selects a log message, calls the shared logger, then cleans up | Logging stub, not a heater-pattern generator |
| `raw_for_test` | `0x5744` copies supplied planar image data when RAM flag `0x118f2a` is set; the later path skips `enhance_image` | External test-image path, not evidence of generated bars or bypass of every downstream stage |
| `IN pattern %s` | Filesystem/directory pattern handling | File matching, unrelated to a printed chart |
| `Zink Test du jour` | Calls barcode-test path `0x309e8` | Not a demonstrated single-dye page |
| `JFIFFINIT` factory JPEG marker | Image-handler branch calls counter-reset helper `0xd868` | State-changing factory initialization, not a harmless color-test switch |

This corrects the stronger implication of the previous menu discovery. The help
strings are real and the dispatcher exists, but those specific pattern entries
are placeholders in this image. Other menu entries do change state; one cannot
treat the entire menu as a no-op. No verified factory chart generator or normal
BLE/RFCOMM invocation was found in the traced paths. That is a bounded negative
finding, not proof that no other firmware build or factory tool can generate one.

The factory marker branch at `0x8e84` calls `0xd868`, which writes zero to the
16-bit field at RAM `0x17ebe8+0x80`, submits the `0xf4`-byte configuration block to
its update helper, and calls `0xcf44` for counter slots 0..15 with a zero value.
The latter routine writes the counter store at RAM `0x179a6c`. We have not fully
traced the asynchronous persistence behavior or named every counter/field.
This is sufficient to reject describing it as a read-only diagnostic feature.

**MCal is a more substantive bypass lead, but still not a generator.** Its setter
at `0x30adc` writes a mode value used downstream (RAM `0x14db20+0x4c`). The normal
image-processing caller at `0x2b5d0..0x2b600` skips RGB LUT interpolation when bit
0 is set. At `0x2c574..0x2c5e0`, the low-two-bit combination `01` selects a helper
that fills three coefficient groups with unit/zero values instead of obtaining
the usual calibration coefficients. Other mode-dependent branches affect MDX
handling. Those are specific bypasses; they do not establish a linear, safe
heater-energy interface or identify an input that energizes exactly one dye.
Neither MCal's full name nor a supported host command is established.

## 5. What FA versus FS now tells us

The app's catalog contains both `HP500-P1L1FA` and `HP500-P1L1FS`. To separate
variant differences from version differences, we downloaded their matching
**2443AR** packages using the catalog's actual URLs. Both list `11-14-2024`;
their catalog `force_update` values differ (FA false, FS true). Their MD5s match
the catalog; signatures were not validated.

[variant-comparison.json](experiments/firmware/variant-comparison.json) records
the download URLs, hashes, all 24 partition comparisons, and exclusive printable
strings. [compare_variants.py](experiments/firmware/compare_variants.py) reproduces
the comparison from local, hash-pinned files.

- **Only `FIRMWARE` and `ROMTAB` partition payloads differ.** Boot, NVRAM, LUTs,
  tone, thermal, and other resource partition payloads are byte-identical in
  this pair. This is not just similarity of filenames or sizes.
- Both inflated main images are 1,765,696 bytes; the scatter table's main-code
  copy length is **304 bytes larger in FS**. Compiler/linker shifts mean this
  does not imply exactly 304 new executable bytes or one sole difference.
- Printable strings of at least eight characters differ only in version, build
  timestamp, and FS's additional `dbgmon thread suspend %x` message.
- The message is backed by executable control flow. In HP500 FS,
  `0x12390..0x123bc` tests a configuration byte at RAM `0x1dbc4c+0x60`; if zero,
  it obtains a thread handle, calls the suspend path, and logs the result. The
  matched FA startup sequence proceeds directly to its main event loop without
  that block.
- Select FS2105 has the analogous check at `0x10e94..0x10ec0`, using RAM
  `0x17ebe8+0xac`. A separate cover-event state machine contains a branch labeled
  `Enable USB Debuging` that looks up `dbg_main` and resumes it if suspended.
  This reinforces the debug-policy interpretation, without verifying a working
  USB console on the physical printer.

**Established:** FA and FS are distinct program builds in the available matched
family; one concrete difference is conditional debug-monitor suspension. The
matched pair's color resources do not differ.

**Probable, not established:** the suffix distinguishes a release/debug-policy
variant rather than fundamentally different color science. This is an inference
from that pair and the analogous Select FS code, not an authoritative naming key
or an exhaustive semantic binary diff.

**Still unknown:** the words behind F/A/S; other behavioral differences; exact
Select FA tables/code; cross-flash compatibility. We should not expand FS as
“signed” or “secure,” or FA as “Android”/“Apple,” without evidence. The Select
software-version getter (`0xbb90`) copies a literal FS version string rather
than translating it based on hardware. The APK's GrandBahama lookup keeps FA/FS
in its catalog key; no normalization has been found. An exact FA package or
authoritative build documentation is still needed to close that gap.

## Reproduction and validation

Use a separate environment with Unicorn 2.1.4; production probe dependencies do
not change. The scripts have no download or printer function. With the documented
packages saved locally:

```sh
python3 -m unittest discover -s experiments/firmware -v
python experiments/firmware/trace_lut.py \
  logs/color-firmware-research/G1L1FS2105AR_1.0.7.rbn > lut-results.json
python3 experiments/firmware/compare_variants.py \
  logs/color-firmware-research > variant-results.json
```

Results: **14 synthetic tests pass**, including existing container tests;
**11,172 RGB pixel comparisons, zero differences** across six raw maps and 19
temperature-selected cases; **19 complete blended maps**, all 19,652 bytes each,
match; selected interval/quantized state also matches; **37 MDX pairs** match.
Pixel cases cover a boundary-focused 11×11×11 RGB grid plus 512 deterministic
random pixels per raw map. The 19 temperature cases cover below/above clamp,
knots, and near-boundary values. This is broad sampled pixel validation, not an
exhaustive test of all 16.8 million RGB inputs or physical printer behavior.

## Implications for CAL-03 and a portable driver

We can now evaluate a requested color through the downloaded firmware's initial
color-map stage and explain why nominal RGB CMY is not a certified isolated-dye
stimulus. We still cannot generate a verified single-dye factory chart from this
evidence. CAL-03 remains useful for comparing end-to-end directional contrast
under matched requested colors; its labels should retain that qualification.

The normal driver should continue delivering the known JPEG representation and
let the printer perform temperature-dependent processing. Applying these same
LUTs on the host could apply a correction twice. The next implementation work
remains the [portable job engine](DRIVER_ROADMAP.md), with an offline simulated
printer and transport adapters for macOS, Linux, and Windows. Exact FA acquisition
and the remaining tone/thermal stages are separate research avenues, not a
prerequisite for that driver milestone.
