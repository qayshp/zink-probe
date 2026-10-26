# Select iOS transport framing and bounded identity test

## Evidence and limits (2026-10-26)

The physical passive test established that our app can open
`com.hp.protocol.lifestyle` on HPISPSLE / G1L1FA2105AR. The encrypted official IPA
still does not expose plaintext transport implementation. Historical Manta/Maui
Objective-C code uses a different framing and is not used to construct a Select
request.

The related `G1L1FS2105AR_1.0.7` firmware contains a separate embedded Bluetooth
controller program. Searching it as part of the main ARM program obscures its
addresses and interrupts strings with record headers. Its contiguous sequence
of 452 `4c fc` controller-load records begins at main-file offset `0x12583a`.
Each record has a one-byte parameter length, a four-byte little-endian destination
address, and that record's program/data bytes. Offline reconstruction reveals
Thumb code and coherent callback tables. No code is loaded into a device.

Reproduce the numeric checks with:

```sh
python3 experiments/firmware/trace_ios_transport.py \
  logs/color-firmware-research/G1L1FS2105AR_1.0.7.main.bin
```

Input SHA-256:
`4cc83261d16ab8078db3a38ae694017c26e6c681e1eca1e9bb41a437704c24ce`.
The tool rejects a different image and checks the callback pointers and strings.
Public numeric results are in
[`ios-transport-results.json`](../experiments/firmware/ios-transport-results.json).
The vendor image, reconstructed bytes and full disassembly remain private.
Disassembly used Capstone in an isolated ignored research environment.

## Callback trace

All addresses below are reconstructed controller addresses, not main-file offsets.
Function names are inferred from callbacks, diagnostic references and code flow.

| Address | Evidence |
| --- | --- |
| `0x224337` | Exact `com.hp.protocol.lifestyle` string |
| `0x2187c8` | iAP connection-up path; calls connection initialization at `0x21b7f0` with configuration pointer `0x224384`, connection type 3 |
| `0x224384 + 4` | Pointer `0x221118` to the framing callback table |
| `0x224384 + 36` | Thumb callback pointer `0x2186cd` to the iAP receive adapter |
| `0x2186cc` | Looks up type-3 connection; forwards supplied bytes/length to `0x21de98` |
| `0x21de98` | Loads connection configuration at +0x6c, framing table at +4, receive function at +0x0c |
| `0x221118 + 0x0c` | Thumb pointer `0x21ca0d`, the HP+ stream receiver |
| `0x21ca0c` | Stateful parser compares bytes against 0x48, 0x50, 0x2b, then accepts length-type values 1–3 |
| `0x221110` | Width table 1,2,4 followed by `HP+` and NUL |
| `0x221118 + 8` | Thumb pointer `0x21c93d`, the HP+ frame sender |
| `0x21c93c` | Prepends three-byte magic, length type and length; dispatches through configured output adapter |
| `0x224384 + 8` | Output table `0x2243ac`, whose first entry is Thumb pointer `0x2188f5` |
| `0x2188f4` | iAP output adapter calls `0x2188ec` / `0x21efa4` with payload and length |

In particular, the receive parser's comparisons are at `0x21ca34` (H),
`0x21ca56` (P), and `0x21ca6c` (+). This is stronger evidence than simply finding
an HP+ string near an iAP diagnostic. The small request uses a one-byte length,
so its interpretation does not depend on multi-byte length byte order.

This remains static evidence from the **FS** image, not a firmware dump of the
physical **FA** unit. It supports the bounded experiment; it does not establish
complete FA/FS equivalence, official iOS app behavior, or printing compatibility.

## Exact permitted experiment

Only HPISPSLE with advertised `com.hp.protocol.lifestyle` gets a separate
**Read firmware once** button. Passive tests remain available and transmit zero.

```
48 50 2b 01 02 04 01
--------- -- -- -----
   HP+    |  |  payload: SYSTEM_ATTRIBUTES_REQ (04), firmware field (01)
          |  payload length = 2
          one-byte length type
```

The payload is already a read-only attribute request in the desktop protocol
allowlist (`src/zink_probe/protocol.py`). No connection-setup, authorization,
resource-allocation, print, settings, or alternative command is attempted.
No fallback to historical `1b 2a` framing is provided.

The app waits for both streams to open, then writes only this immutable seven-byte
frame. Partial writes advance an offset; zero writes await later readiness;
errors close without retry. Subsequent readiness events cannot resend the frame.
The session has a ten-second overall limit and a 4096-byte receive limit.
Backgrounding closes it. Each explicitly initiated test creates a fresh session.

Expected reply: one HP+ frame with payload `05 01 <varuint-length> <firmware>`.
The parser accepts fragmented stream delivery and one- or two-byte frame lengths,
but requires the exact identity response, one printable nonempty firmware string
(up to 128 bytes, optional trailing NUL), no extra fields/trailing bytes, and a
fully sent request. Unknown events, printer errors and malformed replies close
the session with the original raw RX retained. There is no guessed decoding or
automatic follow-up request. A response is compared with EAAccessory firmware
metadata; a mismatch is reported, not silently accepted as matching identity.

## Validation

- Swift offline tests exercise every split of the expected response, short writes,
  zero writes, error writes, no repeated transmission, two-byte frame lengths,
  unexpected/malformed replies and unsolicited response rejection.
- Signed iPhone build and installation passed (build 2).
- Physical request/response succeeded in build 3; see the result below.
  Installing the app never runs this request automatically.
- No printing authorized or performed by this experiment.

## Build 3 UI correction

The user reported that Passive test and Read firmware behaved as one tappable
control on the phone. The supplied 19:17:49Z–19:17:59Z report again showed only
passive observation, TX=0. The two buttons were inside one SwiftUI List row with
automatic button styling; this structure can give them shared row activation.
The passive action runs first and its active-session guard prevents the identity
action from starting. This is an app UI issue, not evidence of protocol rejection
or incorrect user operation.

Build 3 gives both buttons explicit independent styles (`bordered` for passive,
`borderedProminent` for identity) and distinct accessibility identifiers. The
identity wire logic and seven-byte allowlist are unchanged. Signed build and
installation are checked separately from the pending physical tap/response test.


## Physical identity exchange succeeded — build 3

The user supplied the following diagnostic result from the installed app on
2026-10-26. Session started at 19:21:21 UTC, with the response and automatic close
at 19:21:22 UTC (timestamps have one-second resolution, not precise latency).

- App identity: `org.qayshp.zink.SelectAccessoryProbe`, build 3 / `00a896c`.
- Accessory: HPISPSLE, hardware 4138, `com.hp.protocol.lifestyle`.
- TX accepted: **7 bytes**, `48502b01020401`.
- RX: **20 bytes**, `48502b010f05010c47314c314641323130354152`.
- Decoded reply: `HP+`, one-byte length type, payload length 15, response 0x05,
  attribute 0x01, string length 12, ASCII `G1L1FA2105AR`.
- Firmware exactly matched the accessory metadata. Session closed on success.
- No setup, print, settings or follow-up command was sent. No paper consumed.

This physically confirms HP+ stream framing and firmware-attribute request/reply
over the independently signed iOS app's ExternalAccessory session on the FA unit.
The FS static trace is no longer the sole evidence for this narrow behavior.
It does not establish every other command, file transfer, printing, background
reliability, other printer models or App Store distribution approval.

The exact reply is pinned in the Swift regression test, which already exercises
every two-part split of this frame. The preceding identity implementation and UI
fix commits both passed the dedicated iOS CI workflow. Next potential milestone:
a similarly bounded read-only status request, followed by an iOS transport
abstraction; neither requires printing. No additional request was run in this
result-recording step.
