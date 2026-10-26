# macOS and Linux native queue foundation

2026-10-26. The same PAPPL frontend used on Windows now has a reproducible
macOS/Linux build and capture-only integration checks. This is the foundation
for File → Print on these platforms. It does **not** yet install a macOS or Linux
system printer, launch agent, or user service. The existing Python Bluetooth
adapters are unchanged; these tests never connect to a printer.

## Build in a private directory

Use Python 3.11+, a C compiler, make, Git, tar and pkg-config. On macOS, install
Homebrew `pkgconf jpeg-turbo libpng openssl@3`. On Debian/Ubuntu, install
`build-essential pkg-config libavahi-client-dev libjpeg-dev libpng-dev libssl-dev
zlib1g-dev`. The Linux development host was unavailable for this milestone;
the native Linux build is exercised on Ubuntu in CI.

Obtain the upstream source repositories and build an isolated snapshot:

```sh
git clone https://github.com/michaelrsweet/pappl.git build-pappl
git clone https://github.com/OpenPrinting/libcups.git build-libcups
python native/build_posix.py --pappl-source build-pappl \
  --cups-source build-libcups --output logs/native-build
```

The output directory must be new and have no spaces or shell metacharacters.
The builder reads these exact commits using `git archive`, regardless of the
repositories' checked-out branches:

- PAPPL: `02050bdbd4b3e610180c0433f47b7bf2c4569e44`.
- libcups v3.0.3: `f7888eacb576dc13d954c11d0af57af71af3d4a9`.

It applies the existing bounded-copy patch to the private PAPPL snapshot, builds
static PAPPL/libcups libraries, and links `zink-ipp`. System CUPS is neither
replaced nor reconfigured. The reference repositories remain untouched. A private
libcups is needed because this PAPPL revision requires a newer API than macOS's
system CUPS. On macOS, the build explicitly targets the host architecture rather
than upstream's default universal binary, matching the Homebrew libraries.

`build.log`, `build-info.json`, dependency license notices and the executable
remain in the output directory. The executable still depends on the host's TLS,
image and OS libraries: this is a development build, **not a self-contained,
signed or notarized redistributable installer**. Build it on its destination
machine or through the matching CI runner. Windows keeps its existing pinned
NuGet dependency route.

## Offline validation

```sh
python -m pip install '.[images]'
python native/smoke.py logs/native-build/zink-ipp logs/native-smoke
python native/cancel_smoke.py logs/native-build/zink-ipp logs/native-cancel
```

Both commands require new output directories. They start temporary loopback-only
IPP listeners and stop them afterward. No system queue registration or Bluetooth
permission is required. Capture configurations contain no printer identity.

The first check runs four real PAPPL raster jobs: borderless fill and Preserve
edges, each at Normal (90 / 4:2:0) and High (100 / 4:4:4). It verifies 58 × 87 mm
media, one-copy advertising/rejection, capture receipts, both encoding modes,
white margins and separate safe-area previews. Native PDF is not advertised.
This tests direct IPP input, not yet a macOS or Linux application's print dialog.

The second check substitutes a fake worker that only records its PID and sleeps.
It cancels one job whose worker accepts SIGTERM and another whose worker ignores
SIGTERM. Both must become canceled, reap their worker within six seconds and
retain their diagnostic raster. No result or replay is fabricated. The POSIX
frontend now uses `posix_spawn` without a shell, checks cancellation and a
six-minute deadline, allows two seconds for termination, then forces and reaps
a stalled worker. The deadline path shares that termination logic; this test
does not wait six minutes to exercise the deadline itself. As on Windows, a
canceled future live job must retain its durable claims because cancellation
cannot promise to retract a job already accepted by hardware.

Local macOS ARM64 validation passed all four captures and both cancellation
cases (0.263 s and 2.326 s). The portable suite also passed 658 tests with two
optional-binding skips. The native workflow now builds and runs these checks
on both macOS and Ubuntu alongside the existing Windows native job; CI results
are recorded after the run completes.

## Next integration work

1. Add capture-first per-user service/queue installers: launchd plus the macOS
   print system, and a user service plus CUPS on Linux. Preserve separate layout
   profiles and share one durable journal when both eventually become live.
2. Validate actual OS-rendered pages, orientation, media/quality selection,
   cancellation, restart recovery and job retention through those queues.
3. Package native dependencies and platform permissions. Keep queue availability
   separate from physical printer readiness, and never replay uncertain work.
4. Only after those steps, perform a separately authorized physical acceptance
   print through each new OS queue. No paper was consumed by this milestone.
