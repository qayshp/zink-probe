# BLE message verification through iPhone Mirroring

On November 18, 2026 Pacific time, the signed Select Probe update from
`ad954fd51c1e476c5b7fdfa6446ab50f192ae04a` was installed over the existing app
on a physical iPhone. The app and its embedded Share extension retained version
`0.1`, build `16`. Both were tested through iPhone Mirroring using an HP
Sprocket Select with firmware `G1L1FA2105AR`.

| Entry point | Printer replied with the time-invalid flag | Printer switched off |
| --- | --- | --- |
| Main app → Connection help → BLE adapter preflight | **Printer connected; clock sync needed.** | **BLE connection unavailable.** |
| Photos → Share → Select Probe → BLE preflight | **Printer connected; clock sync needed.** | **BLE connection unavailable.** |

In each entry point, the identity check succeeded while the printer was on.
The subsequent preflight negotiated BLE, received a valid printer response,
and stopped at the clock readiness check. The screen directed the user to the
separate clock-sync action in Select Probe. The preflight made no clock or
printer settings changes.

For each unavailable check, the user confirmed the printer was off. The
previously identified printer was retained on the same preflight screen, and
**Run BLE adapter preflight** was tapped again. The unavailable result advised
checking that the printer was on, awake and nearby and that Bluetooth access
was enabled. The run button became available for a manual retry in both entry
points.

The main app's visible report recorded the clock check from `06:59:39Z` to
`06:59:41Z` on November 19, 2026 UTC. It showed two virtual streams and flags
`0x00000001`. The Share extension's visible report identified its own context
and recorded the clock check from `07:35:52Z` to `07:35:54Z` on the same UTC date,
including both virtual streams opening and the readiness stop. These are
observations of the mirrored screen and its diagnostic text. Each check was
read-only, with no image upload, print job, or clock update sent.
