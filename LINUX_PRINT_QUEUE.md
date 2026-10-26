# Linux CUPS capture queue

2026-10-26. ColorBerry (Debian 12, ARM64) now has a native build, an enabled
systemd user service, and a system CUPS queue named
**HP_Sprocket_Select_Preserve_Edges_Capture**. Its display name is
**HP Sprocket Select (Preserve edges) (capture)**. This queue saves prepared
images locally; it cannot be used for physical printing in this milestone.

The actual CUPS PDF → PWG raster → PAPPL → Python preparation path passed
portrait and landscape captures at JPEG quality 100 / 4:4:4. A two-page document
was rejected by the frontend before any worker ran. No Bluetooth session or
physical print occurred. The default printer was not changed, and the queue is
not shared with other machines. macOS system-queue installation remains separate.

See the [captured previews and recorded validation](examples/linux-print-queue/README.md).

## Important status limitation before live Linux printing

The frontend recorded the two-page job as **aborted** (IPP state 8), with no
worker claim or JPEG. However, Debian's CUPS queue reported **completed** (state
9, reason `processing-to-stop-point`). A read-only Get-Job-Attributes request to
CUPS confirmed this mismatch. Successful delivery to the local frontend must not
be confused with successful processing or a physical print.

Resolve and test this failure-reporting behavior before adding a live Linux
queue installer. This capture milestone deliberately has no live-mode switch,
printer identity, Bluetooth pairing step, or automatic retry. The exact cause
of the CUPS/backend status translation has not yet been traced.

## Capture-first setup

The [POSIX build guide](POSIX_PRINT_QUEUE.md) covers the pinned private native
libraries. On Debian, the system spooler additionally needs `cups cups-client
cups-filters`; `libavahi-client-dev python3-venv` support this build/environment.
On ColorBerry those six requested packages and their package-manager dependencies
were installed with explicit authorization. No general system upgrade, password
change, SSH hardening, user-group change or unrelated service repair was done.
The separately built libcups/PAPPL libraries remain private; they do not replace
the system CUPS libraries.

Create a Python environment and install this project with its image extra, then:

```sh
python native/install_linux_capture.py \
  --binary /absolute/path/native-build/zink-ipp \
  --python /absolute/path/venv/bin/python
```

The installer defaults to Preserve edges, port 8632, and
`~/.local/share/zink-probe/preserve-edges-capture`. It creates private capture
directories and an enabled `zink-select-preserve-edges-capture.service` under
`~/.config/systemd/user`. It runs as the normal user. The service requests
`NoNewPrivileges` and allows Unix/IP socket families; its capture configuration
contains no device address or identity. It listens only on `127.0.0.1`.

`--plan-only` displays the paths, unit and registration command without making
changes. The installer refuses existing data or an existing unit rather than
overwriting jobs. `--layout fill --port 8631` can prepare a distinct borderless
capture profile; only Preserve edges was installed on ColorBerry.

The installer prints the separate CUPS registration command. On Debian,
`lpadmin` is under `/usr/sbin` and registration requires administrator access:

```sh
sudo /usr/sbin/lpadmin -p HP_Sprocket_Select_Preserve_Edges_Capture -E \
  -v ipp://127.0.0.1:8632/ipp/print -m everywhere \
  -o printer-is-shared=false -o printer-error-policy=abort-job \
  -D 'HP Sprocket Select (Preserve edges) (capture)'
```

Registration submits no document and does not select a default printer. No
password is handled or stored by the installer. ColorBerry's normal user was
denied registration, so the one queue-registration action was separately
authorized and performed as administrator. The service itself stayed unprivileged.

User lingering was already enabled on ColorBerry; it was not changed. The service
was tested across a restart, not an operating-system reboot. On systems without
lingering, the user manager may stop after logout; choose the desired lifecycle
before treating the queue as continuously available.

## Actual-spooler validation

```sh
python native/validate_linux_capture.py \
  --root ~/.local/share/zink-probe/preserve-edges-capture \
  --output logs/linux-cups-validation
```

This generates synthetic portrait, landscape and two-page PDFs, requests the
advertised 58 × 87 mm media and High quality, then submits them through `lp`.
Before submission it verifies capture mode, absence of device identity, the
exact CUPS endpoint, the running service's arguments, and idle queues. Those
guards remain active with Python optimization enabled. Existing completed
captures are retained and counted separately; incomplete worker claims block
the check. Use a new output directory each time.

The validator requests job states explicitly from the frontend and from CUPS,
records both, and checks that the rejected document adds no worker receipt or
prepared image. The initial development check omitted the requested job-state
attribute and timed out after a successful portrait capture. That result was
retained; the corrected run passed with two more captures and one rejection.
There are three synthetic completed captures in the installed directory.

Captures are under `jobs/<id>/image.jpg`, `preview.png`, `safe-area-preview.png`
and their manifests/receipts. The violet safe-area guide is never in the JPEG.
The complete rendered page receives the conservative inset; cropping already
performed by the application cannot be undone by the queue. Physical edge
retention has not been validated by this capture test.

The failed two-page job's first decoded raster remains under `incoming` for
diagnosis. No engine journal or protocol frame log was created. Do not turn a
capture directory into a live configuration or replay its existing files.

## Service management and remaining work

```sh
systemctl --user status zink-select-preserve-edges-capture.service
journalctl --user -u zink-select-preserve-edges-capture.service
lpstat -t
```

An idle-service restart changed the process ID while preserving all 19 captured
artifact/diagnostic files byte-for-byte. The terminal job states persisted and
no work replayed during a five-second observation after the listener returned.
The service remains enabled/running and the CUPS queue idle. This is not a test
of restarting during upload or retracting an accepted hardware job.

Next: resolve the CUPS failure-state mismatch, extend actual-spooler cancellation
and interrupted-job recovery tests, then design explicit live activation with a
shared durable journal. Desktop application UI interaction and physical Linux
printing remain unvalidated. No additional sheet is needed for the next steps.
