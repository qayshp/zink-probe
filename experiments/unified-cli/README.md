# Unified CLI validation, 2026-10-25

Implementation: `73d5f815edf5c549839a1fa4808840ef0db05d3e`.
Usage and recovery contract: [UNIFIED_CLI.md](../../UNIFIED_CLI.md).

No real submission was attempted and no sheet was printed. Hardware access
used only `zink status`; all submission and recovery scenarios used simulated
printers. Raw frames, target identifiers, job journals and helper scripts remain
under ignored private `logs/`. The committed
[validation summary](validation-2026-10-25.json) contains sanitized evidence,
trace hashes and source fingerprints.

## Software checks

- Final local macOS Python 3.14.8 suite: **621 passed, 2 skipped**.
- Unified CLI suite: **53 passed**, covering both quality-90 4:2:0 and quality-100
  4:4:4 plans, full offline-to-simulator workflows, exact payload transfer,
  changed/corrupt bundles and plans, unchanged UUIDs, duplicate blocking,
  unresolved printer claims, identity/battery/pause preflight refusals,
  connection failures, lost replies, cancellation, deadline expiry and read-only
  reconciliation. A malformed Huffman table with recalculated hashes tests full
  decode failure separately from header/hash validation.
- Previous rendering research: **8 tests passed**; bounded calibration
  transaction tests: **11 passed**.
- Ruff lint/format, installed command workflow and portable wheel build passed.
- [Six-host/Python CI run](https://github.com/qayshp/zink-probe/actions/runs/40174504117)
  exercises all supported commands with a simulation-only plan, plus the full
  suite, existing research/adapter tests and wheel build. **All six jobs passed**
  for implementation commit `73d5f81`; [machine-readable results](ci-2026-10-25.json)
  retain job IDs, conclusions and test summaries.

| CI host | Python versions | Main suite, each version | Additional native checks |
| --- | --- | --- | --- |
| macOS | 3.11, 3.14 | 619 passed, 4 skipped | 2 passed after installing macOS extras |
| Linux | 3.11, 3.14 | 619 passed, 4 skipped | 1 passed after installing Linux extras |
| Windows | 3.11, 3.14 | 620 passed, 3 skipped | Native ABI checks included in main suite |

All six installed-CLI workflows and wheel builds passed. Windows Python 3.11
took about seven minutes for the full suite; its durable journal tests completed
within the existing CI limit. No timeout was relaxed or failed case skipped.
The follow-up commit contains documentation/evidence only, with no runtime change.

## Read-only physical checks

| Host | Result | Frames |
| --- | --- | --- |
| Mac, arm64, Python 3.14.8 | Two initial sessions and one session on the committed source passed | 105 requests / 105 replies |
| Surface, Windows ARM64, Python 3.12.10 | Two initial sessions and one session on the committed wheel passed | 105 requests / 105 replies |
| ColorBerry, Linux aarch64, Python 3.11.2 | Pairing preflight passed, then connection timed out on two separately invoked attempts, with 10- and 30-second I/O limits | 0 protocol frames |

Sessions were sequential across hosts. Each successful session sent 35 requests
(266 framed bytes), received 35 matching replies (870 framed bytes), and closed
without an adapter close error. Both successful hosts reported:

- Expected protocol identity and firmware `G1L1FA2105AR`, super-model 18643;
- negotiated message size 1000 and a 227-byte capability file;
- battery 100%, charging, idle, no flags and an empty queue;
- page counter 12 and calibration counter 2, unchanged;
- unchanged configuration within and between each host's sessions.

The offline audit validated **all 210 attempted requests** against the existing
read-only allowlist, correlated all 210 replies, and found no pending request
at the end. There were no print allocation, JPEG upload, job-property write,
configuration-write, reset or diagnostic print commands.

The initial checks preceded small output-label/error-trace improvements. Every
attempt records the actual running source fingerprint. The final one-session
Mac/Surface checks verified hashes of every installed Python source against
commit `73d5f81` before opening Bluetooth. No adapter or status-request logic
changed between initial and final checks.

ColorBerry's current connection failure is unresolved. No re-pairing, controller
reset, trust/power change or device setting change was made. The CLI's earlier
version reported those timeouts in JSON; the final version also records status
failures in its private trace, covered by an automated zero-frame failure test.
The summary retains the external error/exit result alongside the zero-frame
audits so that an absence of trace errors is not mistaken for a successful
connection. Prior Linux adapter read-only success remains documented
[separately](../linux-adapter/README.md); it is not a current unified-CLI hardware
success claim.

Physical printing through the portable engine/native adapters remains untested.
The earlier CAL-02/CAL-03 printing evidence used the bounded research sender.
Portable discovery/profiles, packaging and OS queue integration remain future
work; a printing acceptance test needs separate authorization.
