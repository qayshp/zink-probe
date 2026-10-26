# Preserve edges and safe-area previews

Updated 2026-10-26. This is an opt-in image-placement policy for the Select. The
default **Borderless fill** path and its historical JPEG bytes are unchanged.
The second queue is now installed on Surface **in capture mode only**, with
actual Windows spooler validation. No printer connection, settings change or
physical print was made for this feature.

## Three layouts

| Layout | Placement | Tradeoff |
| --- | --- | --- |
| Borderless fill (`fill`, default) | Uniformly cover the 768 × 1152 canvas, with a centered crop. | Uses the whole canvas; source crop and further physical edge loss are possible. |
| Fit (`fit`) | Uniformly fit the entire source on the full canvas. | Different aspect ratios get white padding; a 2:3 source still reaches the canvas edges. |
| Preserve edges (`preserve-edges`) | Uniformly fit the entire source in a centered 672 × 1056 box, inset 48 pixels on every side. | Adds white margins and reduces image size to keep content away from the edges. |

For a 768 × 1152 portrait source, Preserve edges produces a **672 × 1008** image
within the unchanged 768 × 1152 JPEG: 48 pixels left/right and 72 top/bottom.
This is 87.5% of the original linear size. Wider/taller sources retain their
aspect ratio and get additional padding on the non-limiting axis. EXIF
orientation and sRGB conversion happen before layout, just as before.

The inset is a conservative starting policy, **not an exact printer crop
correction or a guaranteed safe boundary**. The four 48-pixel reference crosses
survived the [CAL-02 sheet](experiments/calibration/PHOTO_ANALYSIS.md). That sheet
suggested unequal missing edge depths around 20/12/12/33 input pixels, with
several-pixel measurement uncertainty. We use neither those asymmetric offsets
nor a promised physical millimeter border. Repeatability on other sheets/units
and the final Preserve edges appearance remain untested.

## Offline preview

```sh
zink prepare photo.jpg prepared-preserve --mode preserve-edges --quality 100 --subsampling 4:4:4
```

Open `prepared-preserve/preview.html`. All three layouts show their decoded JPEG
pixels, using identical encoding settings. **Show safe-area guides** toggles a
violet outline and tinted outer band. The band highlights content more exposed
to trimming; it does not assert that everything there will be lost. The guide
does not simulate the printer's color, heat response or exact paper edge.

`safe-area-preview.png` contains the selected image plus that guide for convenient
viewing. `preview.png` and all three layout PNGs contain only decoded image pixels.
**No guide is embedded in `image.jpg` or `raster.png`.** The saved-job engine
continues to snapshot only the checked `image.jpg`, never a guide PNG. The bundle
manifest records the policy (`select-conservative-48px-v1`), box, selected mode,
geometry, JPEG settings, and artifact hashes.

The API accepts `PreparationOptions(mode="preserve-edges")` and exposes
`safe_area_preview(prepared)` as a separate PNG-producing function. The existing
`PreparedImage` fields and fit/fill pixel outputs are unchanged. The comparison
API now returns three dictionary entries instead of two. Earlier two-layout
bundles remain accepted by saved-job planning.

See the [synthetic portrait example](examples/preserve-edges/README.md). It uses
no personal photograph or printer connection.

## Windows File → Print option

The installer can prepare a second choice, **HP Sprocket Select (Preserve edges)**,
alongside the existing **HP Sprocket Select** borderless queue. Selection happens
in the printer list; we do not depend on a custom checkbox being exposed by every
application's print dialog. Add `-PreparationMode PreserveEdges` to the existing
installer arguments. The default is still Capture; activating Live requires the
existing borderless Live configuration and the same device identity.

| Profile | Local port by default | Task | Runtime/private data |
| --- | --- | --- | --- |
| Fill | 8631 | `ZinkProbe-Select` | `%LOCALAPPDATA%\ZinkProbe` |
| Preserve edges | 8632 | `ZinkProbe-Select-PreserveEdges` | `%LOCALAPPDATA%\ZinkProbe\preserve-edges` |

The second profile has its own environment, binaries, spool and job artifacts.
Both Live queues use the **existing borderless engine journal**. This preserves
the one-active-job/uncertain-job guard across layout choices. Simultaneous jobs
are not a scheduled multi-job queue: a competing job may fail its connection,
readiness or shared-journal check and must not be blindly resubmitted. Independent
hosts and unrelated CLI journals still cannot coordinate through this journal.

Worker configuration adds `preparation_mode` (`fill` or `preserve-edges`, missing
means `fill`) and an optional absolute `journal_path`. Invalid values fail before
claiming a job. Capture mode never opens a transport or journal, including a
shared journal. Claims and receipts record the layout; job artifacts include
both a plain decoded preview and a separate safe-area PNG.

**The application controls the original photo framing.** If Windows Photos or
another application already crops the image to fill the page, the bridge cannot
recover those pixels. Choose the application's fit/whole-image option when that
matters. The Preserve edges queue insets the **complete rendered page**. Its
extra margin is applied after the application's preview; safe-area guides are
provided in our offline HTML/PNG previews, not injected into Windows' native
print dialog. Inspect a capture result to preview that exact application route.

The second queue is now installed on Surface as **HP Sprocket Select (Preserve
edges) (capture)**. The [installation report and actual captured previews](examples/windows-preserve-edges/README.md)
record successful portrait/landscape jobs, two-page rejection, and unchanged
original borderless runtime/journal. The [Windows guide](WINDOWS_PRINT_QUEUE.md)
explains capture-first installation.
`-PlanOnly` displays names/paths/ports without touching files, queues, tasks,
permissions or Bluetooth; it is a layout plan, not full prerequisite validation.

## Validation

The automated tests cover all three layouts through saved-plan creation and a
simulated full transfer, exact payload reconstruction, EXIF-before-layout,
whole-source retention at multiple aspect ratios, white margins and guide-only
pixel changes. Existing CAL-02/CAL-03 JPEG golden tests keep defaults byte-exact.
Two worker profiles sharing an unresolved journal are tested to perform at most
read-only simulated preflight, with no image upload or print-start request.

The native Windows smoke test runs the real local IPP listener and PAPPL raster
pipeline for both layouts at Normal and High quality, in **capture mode only**.
It checks margins, sidecar previews, supported media and copy rejection. A
PowerShell test checks distinct installer names/ports/tasks/runtime paths without
installing anything. The portable suite runs on macOS, Linux and Windows; no
test in either CI workflow accesses a printer.

### Recorded results

Implementation [`cfa380e`](https://github.com/qayshp/zink-probe/commit/cfa380eefcbd9a537044dcc898c0da687515d6dd)
passed **658 tests with two expected optional-binding skips** locally on macOS,
plus 8 earlier image-research tests and 11 calibration-transcript tests. Lint,
formatting and wheel build passed. Default calibration JPEGs remained byte-exact.

The [portable CI run](https://github.com/qayshp/zink-probe/actions/runs/40222249271)
passed all six jobs for that implementation:

| Platform | Python 3.11 | Python 3.14 |
| --- | --- | --- |
| macOS | Passed | Passed |
| Linux (Ubuntu) | Passed | Passed |
| Windows | Passed | Passed |

Each job covers the three-layout unit/integration suite, earlier image and
calibration tests, installed CLI preparation, simulated submission and wheel
build. The unified CLI workflow now prepares with `preserve-edges`; its saved
payload is reconstructed byte-for-byte by the simulated printer.

The [native Windows workflow](https://github.com/qayshp/zink-probe/actions/runs/40222249266)
passed its offline installer-layout check, native build and four actual loopback
IPP **captures**: fill/preserve-edges, each at Normal and High. PAPPL supplied
1370 × 2055 pages; Preserve edges placed the complete page into
`[48, 72, 720, 1080]` on the 768 × 1152 output, while fill retained zero padding.
Both profiles rejected two copies. No Bluetooth was opened. The downloaded
capture artifacts' payload hashes and decoded-preview equality were independently
verified. The [public result summary](examples/preserve-edges/native-capture-validation.json)
contains only synthetic-fixture geometry/encoding/results, no private photo or
device identifier.

The committed portrait example's selected JPEG is **176,012 bytes**, quality 100 /
4:4:4, SHA-256 `eb973cdb2d7ecb17423014898660e17cc801e71c23e20fd969fe3b620af9cfcb`.
All bundle hashes and HTML links were verified. The PNG comparison was visually
inspected. The embedded browser refused local `file:` navigation, so interactive
HTML toggle behavior was not browser-tested in this run; its markup/CSS were
inspected without bypassing that restriction. No claim of physical edge retention
follows from those original offline tests. On-Surface capture installation and
validation were subsequently completed on 2026-10-26 as linked above. The new
[macOS/Linux native build](POSIX_PRINT_QUEUE.md) also validates both layouts in
temporary local IPP capture servers, without installing OS queues or printing.
