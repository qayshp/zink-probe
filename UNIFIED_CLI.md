# Unified Select CLI

`zink` joins offline preparation and the portable single-job engine to the
macOS, Linux and Windows RFCOMM adapters. Python 3.11+ is required. This is a
command-line backend, not an installed OS print queue.

## Install

Inside a virtual environment in this repository:

| Host | Command |
| --- | --- |
| macOS | `python -m pip install -e ".[images,macos]"` |
| Linux with BlueZ | `python -m pip install -e ".[images,linux]"` |
| Windows 64-bit x64/ARM64 | `python -m pip install -e ".[images]"` |
| Offline work on any of the three | `python -m pip install -e ".[images]"` |

Use `zink --help` or `python -m zink_probe.unified_cli --help`. Previous
`zink-prepare`, `zink-simulate`, `zink-*-check` and diagnostic `zink-probe`
commands remain supported. Native libraries load only for the selected adapter;
help and simulation do not load or open Bluetooth. Planning/submission require
Pillow to decode-check JPEGs; read-only status does not need Pillow.

## Commands

| Command | Purpose | Printer access |
| --- | --- | --- |
| `prepare INPUT BUNDLE` | EXIF/sRGB, fit/fill, JPEG and previews | None |
| `plan BUNDLE JOB` | Snapshot JPEG; bind printer, name, copies and stable UUID | None |
| `show JOB [--journal FILE]` | Validate job; display optional journal record | None |
| `status --address MAC --device-id ID` | Identity, firmware, battery, status, queue, config and counters | Read-only |
| `submit JOB --address MAC --journal FILE` | Preflight, allocate, upload and observe this one job | **Prints for a real plan** |
| `reconcile JOB --address MAC --journal FILE` | Observe an already attempted job; never resume or resend | Read-only |

Status and reconciliation enforce the diagnostic request allowlist before I/O.
Status defaults to one fresh connection; `--sessions 2` or `3` adds checks with
two-second gaps, stopping at the first failure. Configuration and counters must
remain unchanged. JSON includes status/battery, queue, firmware and counters;
the private trace retains full identity, capability and configuration replies.

Real operations need existing OS pairing, the protocol-reported **Classic MAC**,
and the known **32-hex protocol device ID**. The plan carries the ID for later
submission/reconciliation. Use existing diagnostic discovery/probing to obtain
trusted values; portable discovery/pairing are separate future work. A macOS BLE
UUID is not a Classic MAC. `--transport auto` chooses this host's native adapter;
explicit `macos`, `linux`, or `windows` must match the running OS. `--adapter`
optionally selects Linux `hciN` or a Windows local-radio MAC. Pairing and radio
power are never changed by these commands.

## Entirely offline example

These commands work on all three systems and cannot contact a printer:

```sh
zink prepare examples/image-preparation/source.png prepared-photo --mode fill
zink plan prepared-photo simulated-job --simulated
zink status --transport simulated
zink submit simulated-job --journal simulated-jobs.sqlite
zink show simulated-job --journal simulated-jobs.sqlite
zink reconcile simulated-job --journal simulated-jobs.sqlite
```

Open `prepared-photo/preview.html` before planning. Successful simulated
submission reports `payload_bytes_match: true` and `print_start_count: 1`.
Repeating submission fails before opening a connection. The terminal
reconciliation above reads the saved completed record locally.

## Real job workflow

Replace `PRINTER_MAC` and `PROTOCOL_DEVICE_ID` with trusted values. Everything
through `show` below is offline except `status`, which only reads the printer:

```sh
zink status --address PRINTER_MAC --device-id PROTOCOL_DEVICE_ID
zink prepare photo.jpg prepared-photo --mode fit --quality 100 --subsampling 4:4:4
zink plan prepared-photo photo-job --device-id PROTOCOL_DEVICE_ID --name PHOTO --copies 1 --allow-alternative-sampling
zink show photo-job
```

**This next command prints.** Use it only when ready to spend the selected sheets:

```sh
zink submit photo-job --address PRINTER_MAC --journal select-jobs.sqlite
```

Keep and reuse that journal for this printer. If the outcome is uncertain:

```sh
zink show photo-job --journal select-jobs.sqlite
zink reconcile photo-job --address PRINTER_MAC --journal select-jobs.sqlite
```

Preparation defaults remain quality 90, baseline JPEG, optimized Huffman and
4:2:0. Alternate 4:2:2/4:4:4 sampling needs explicit opt-in when planning.
Quality 100 / 4:4:4 has one earlier physical CAL-03 print; it is not a proven
visual improvement or an engine quality setting. JPEG bytes transfer unchanged.
No PhotoFix, thermal compensation, sharpening, speed or heater controls are added.

## Persistence and recovery

Plans contain `image.jpg` and `job.json`. The checksummed intent binds a
canonical UUID, printer identity, real/simulated mode, copies, name, JPEG hash,
size, header properties and declared encoder quality. Bundle hash/size and
encoding metadata are checked first. Creating/loading a plan parses headers
and fully decodes the image; this does not guarantee rejection of every possible
entropy error by the decoder. Encoder quality is declared metadata, not inferred.
Planning/submission never re-encode. New directories are required; later edits
to the source bundle cannot change the planned JPEG.

Checksums detect mistakes, not a hostile author rewriting checksums too. Keep
plans and journals trusted; do not edit them to force retries. A simulated plan
cannot select a native adapter or Bluetooth address. A real plan cannot switch
to simulation at submission: create a separate simulation-only plan.

The same local ID is never reallocated within a journal. An unresolved printer
claim blocks different plans too; the engine's atomic SQLite claim still guards
races after the CLI's early check. A possibly sent mutation followed by timeout,
lost reply or cancellation records uncertainty and closes the owned connection.
There is no automatic retry, reconnect, upload resume, cancel or force-clear.
Creating a new plan is an intentional new job, not recovery. Independent journals
on other computers do **not** provide cross-host duplicate prevention. Coordinate
printer ownership and retain the original journal when changing hosts.

`--timeout` bounds each exchange (15 seconds by default);
`--observation-timeout` bounds completion observation (180 seconds);
`--operation-timeout` bounds open/preflight/upload/observation together (300
seconds). Values must be finite, positive and at most 300. Status has its own
`--session-timeout` (90 seconds). A hung synchronous OS call can exceed Python's
deadline. Interrupts retain pending state. If the allocation reply was lost,
read-only reconciliation may remain uncertain because the remote job ID is
unknown. A page-counter guess does not clear that claim.

`completed` is conservative protocol evidence, not visual confirmation of a
sheet: `physical_ejection_confirmed` stays false. A close error is surfaced even
after established protocol completion.

## Output and privacy

Commands emit JSON; help/argument messages use argparse conventions. Summaries
omit printer identity/custom device name; those remain in private plans/traces.
The user-supplied job name appears in the local job summary.

| Exit | Meaning |
| --- | --- |
| 0 | Operation succeeded; submission/reconciliation established completion |
| 1 | Validation, connection, preflight, rejection or other failure; inspect JSON |
| 2 | Invalid command-line arguments |
| 3 | This attempted job remains unresolved/stopped/uncertain |
| 130 | User interruption; inspect journal before further action |

Status success means a valid snapshot, not necessarily print readiness. `show`
succeeds when inspection succeeds even if the record is uncertain. Refusal when
a *different* job owns the unresolved printer claim returns 1.

Traces default to `logs/<UTC>-zink-<command>-<random>.jsonl`, exclusively created
and immediately flushed. New plans/directories/files request POSIX modes
0700/0600; Windows follows the containing account directory's ACL. Traces can
include identity/configuration data and entire image uploads. Keep plans,
journals and traces private. Existing files are never overwritten.

## Validation boundary

The new tests cover preparation through simulated completion, 90/4:2:0 and
100/4:4:4, exact payload transfer, damaged/changed plans, source independence,
native dispatch without Bluetooth, wrong identity/battery/paused preflight,
connection failures, lost allocation/status replies, cancellation/deadlines,
duplicate/unresolved guards and allowlisted reconciliation. CI runs the installed
CLI workflow on macOS/Linux/Windows with Python 3.11 and 3.14. Hardware validation
for this milestone is read-only: no sheets are printed by the new CLI.
See [recorded software/hardware results and the frame audit](experiments/unified-cli/README.md),
including the unresolved ColorBerry connection timeouts.

See [portable engine](PORTABLE_JOB_ENGINE.md), [preparation](IMAGE_PREPARATION.md),
[macOS](experiments/macos-adapter/README.md), [Linux](LINUX_ADAPTER.md) and
[Windows](WINDOWS_ADAPTER.md) for the underlying contracts and limitations.
