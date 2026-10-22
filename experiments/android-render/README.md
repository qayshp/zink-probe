# Offline Android render harness

This research-only app calls the **original compiled HP classes** through
reflection. It neither includes vendor source/binaries nor reimplements their
image processing. It has no Bluetooth/network permissions and never creates a
printer client. It is separate from the macOS probe and is not a printing API.
See [the findings](../../ANDROID_RUNTIME.md) and [captured summary](evidence/summary.json).

## Requirements and build

Used locally: macOS ARM64, Java 21, Android SDK platform 35, build-tools 36.0.0,
and a fresh Android 16 ARM64 emulator. No root is required. The vendor base APK
and matching arm64/density/language splits must already be installed in the
research emulator, without launching its application. This harness specifically
expects package `com.hp.impulse.sprocket` 3.0.2921.1 / 74251, whose base SHA-256 is
`6395bd47fa7c669dd5fbc4a5408a4d54dd8c1841e8581be898f3bf90caaa405c`.
Do not use an unrelated APK or a personal/physical device.

From the repository root:

```sh
experiments/android-render/build.sh
```

`ANDROID_SDK_ROOT` can override the default macOS SDK directory. Build products
and the disposable research signing key are placed in ignored
`logs/android-runtime/build/`. The public research-only keystore password in the
script protects no production identity. There are no vendor signing keys.

Use an explicit research emulator serial for every adb operation. The run used
`emulator-5580`; confirm `adb -s emulator-5580 shell getprop ro.boot.qemu` returns
`1` and that this is the dedicated research AVD before proceeding.

```sh
adb -s emulator-5580 shell svc bluetooth disable
adb -s emulator-5580 shell svc wifi disable
adb -s emulator-5580 shell svc data disable
adb -s emulator-5580 install -r logs/android-runtime/build/render-probe.apk
adb -s emulator-5580 shell am force-stop dev.zink.renderprobe
adb -s emulator-5580 shell am start -n dev.zink.renderprobe/.MainActivity --es run full-default
adb -s emulator-5580 logcat -d -s ZinkRenderResearch:I
```

Wait for `COMPLETE`, then capture the outputs. The worker reports per-case errors
in JSON rather than hiding them; completion alone is not a passing result.

```sh
adb -s emulator-5580 exec-out run-as dev.zink.renderprobe tar -cf - files/results-full-default > logs/android-runtime/full-default.tar
```

For the controlled pointer-tagging comparison, rebuild only the harness:

```sh
DISABLE_POINTER_TAGGING=1 experiments/android-render/build.sh
```

Repeat install/force-stop/start with run label `no-pointer-tags`, then capture
`files/results-no-pointer-tags`. The normal manifest leaves tagging at the OS
default. The alternative build only adds the per-app pointer-tagging opt-out to
the generated manifest; it does not modify the vendor APK or system settings.
This is a diagnostic experiment, not a production compatibility recommendation.

The harness explicitly sets the Lanczos preference for each route. Its initial
`DEFAULT_LANCZOS` log reports current stored state: the first clean run was true,
while a later run can report false because the preceding matrix tests stored it.
Thus it must not be interpreted as a clean-install default on every launch.

`--ez inspectOnly true` evaluates profiles and serializes two synthetic message
bodies without rendering images. Output `offline-messages.json` explicitly records
`transmitted: false`. No serialization method sends anything. The main harness
also performs this offline inspection before its rendering cases.

## Analysis and retained evidence

Extract each captured archive with a safe tar extractor into
`logs/android-runtime/full-default/` and `logs/android-runtime/no-pointer-tags/`.
The archives contain `files/results-<run>/`. Place the captured
`offline-messages.json` directly under `logs/android-runtime/`.

Use an isolated Python environment with Pillow, NumPy, and Matplotlib:

```sh
python experiments/android-render/analyze.py logs/android-runtime experiments/android-render/evidence
```

The analyzer asserts case counts, absence of errors, dimensions, JPEG sampling,
metadata, and full-preprocessing byte equality; computes enhancement differences;
and creates a comparison figure from synthetic images. Committed evidence contains
only derived facts, hashes, and the synthetic figure. APKs, native libraries,
full screenshots/logcat, output JPEGs, and private archives stay in ignored logs.
The model enum results establish runtime values for this APK, not other devices'
physical print compatibility.

The existing physical-printer probe's allowlist is unchanged. Do not bridge a host
Bluetooth adapter, instantiate vendor transport clients, or turn this harness into
a device print experiment without separate authorization.
