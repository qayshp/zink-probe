# Read-only BLE preflight tests

Run from the repository root on macOS:

```sh
mkdir -p build
swiftc ios/PrintCore/*.swift ios/BLECore/*.swift ios/BLESubmission/*.swift \
  ios/SelectAccessoryProbe/NativeBLEAdapter.swift \
  ios/SelectAccessoryProbe/BLEPreflightController.swift \
  ios/ble-preflight-tests/main.swift -o build/ios-ble-preflight-tests
build/ios-ble-preflight-tests
```

The test packet peer independently assembles requests and fragments responses,
then supplies payload replies from the existing deterministic `SimulatedPrinter`.
The production `BLECoordinatorSession.preflight` composition remains intact.
Only the packet IO is replaced. No Bluetooth manager, physical printer or paper
is used.

Coverage includes 12 MTU/ACK/callback-order combinations; full identity, firmware,
capability, status, queue and metric reads; strict refusal for clock-invalid and
paused status; wrong identity/firmware; malformed/replayed or missing responses;
every packet boundary with disconnect, screen dismissal and Share background
cancellation; repeated start/stop and harmless late callbacks; 15-second setup
success and the 90-second setup deadline. Tests require zero allocation, image,
print, clock or settings requests and verify the native submission entry point
still throws its disabled error before creating an authorization or connection.

The production `BLEPreflightController` is exercised with its narrow fake-adapter
interface: passive construction, invalid firmware, exact selected UUID/firmware,
duplicate taps, stale callback generations, success versus strict readiness
refusal, cancellation/dismissal/background stop, an inline callback while
stopping, sanitized unknown errors, and owner release. These tests require no
SwiftUI view or CoreBluetooth manager. The fake interface has no print, recovery,
clock or settings operation.

Terminal-message checks use the production packet bridge and parsed readiness
metadata, then present the resulting terminal pump through the controller's fake
adapter seam. They distinguish an unavailable connection, BLE setup failure,
interrupted BLE communication, and a connected printer refusing readiness.
Clock-only status has its own message; a clock flag combined with other flags,
a busy/current-job/queue state, low battery, or unknown power also reports the additional
blockers. Paused, low-battery and nonempty-job-list replies remain connected
readiness refusals. An incomplete reply containing a clock bit, an invalid
battery percentage, or an unknown pause value must not recommend a clock fix.
Tests also verify that failure returns control without
automatic retry, a later explicit rerun can succeed, diagnostic identities stay
private, and no clock or print request is added. Simulated connection deadlines
exercise the shared setup deadline, not CoreBluetooth's native ten-second stage.

A clock-invalid refusal is expected readiness behavior. It is not treated as a
transport failure or permission to set the printer's clock. Such a refusal does
not produce `VerifiedPrinter` evidence and does not continue to queue/metric
reads. Successful read-only preflight is not print authorization.

These deterministic tests cannot establish real CoreBluetooth callback behavior,
phone/extension lifecycle behavior, printer readiness or physical printing.
