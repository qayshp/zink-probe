# SELECT-CAL-03 prepared image package

Prepared and checked offline; **not physically printed**.

![Candidate JPEG](python.jpg)

See [the experiment design, measurements, limitations and reproduction steps](../REVISION_3.md).

- `source.png`: exact generated RGB patterns.
- `python.png`, `python.jpg`: prepared bitmap and candidate print payload.
- `android.png`, `android.jpg`: original Android renderer comparison.
- `android-photofix.png`, `android-photofix.jpg`: enhancement-requested comparison.
- `manifest.json`: patch coordinates, requested colors and source/payload hashes.
- `comparison.json`: six Android cases and decoded-image differences.
- `verification.json`: checked controls and all decoded-JPEG line baselines.

The plain Python JPEG is 96,490 bytes, SHA-256
`f21f5840422fc73f3b535ef3e69381d2a2d91b1ea3a4dce575076d38c68d4d48`.
Use the decoded JPEG as the measurement baseline; one-pixel CMY stripes already
lose substantial channel modulation in the JPEG's color subsampling.
