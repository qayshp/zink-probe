# SELECT-CAL-03 prepared image package

Prepared and checked offline. **A quality-100 4:4:4 encoding subsequently printed
successfully on 2026-10-24, with B / TWO first.**

![Actual printed JPEG encoding](../../jpeg-quality/q100-444-optimized.jpg)

See [the experiment design, measurements, limitations and reproduction steps](../REVISION_3.md).
The [physical print record](../CAL03_PRINT.md) explains the exact selected encoding,
rejected transactions, successful upload and operator observation. The original
quality-90 artifacts below remain unchanged and were not the bytes printed.

- `source.png`: exact generated RGB patterns.
- `python.png`, `python.jpg`: prepared bitmap and candidate print payload.
- `android.png`, `android.jpg`: original Android renderer comparison.
- `android-photofix.png`, `android-photofix.jpg`: enhancement-requested comparison.
- `manifest.json`: patch coordinates, requested colors and source/payload hashes.
- `comparison.json`: six Android cases and decoded-image differences.
- `verification.json`: checked controls and all decoded-JPEG line baselines.
- `quality100-verification.json`: repeated-control and line baselines for the printed encoding.
- `print-evidence.json`: sanitized physical transaction evidence, including every upload acknowledgement.

The plain Python JPEG is 96,490 bytes, SHA-256
`f21f5840422fc73f3b535ef3e69381d2a2d91b1ea3a4dce575076d38c68d4d48`.
That original encoding loses substantial channel modulation in one-pixel CMY
stripes. For the physical sheet, use the linked quality-100 4:4:4 payload and its
own `quality100-verification.json` references instead.
