# Offline CAL-03 JPEG quality experiment

The same prepared CAL-03 RGB bitmap, encoded with different JPEG settings.
**Research candidates only: no printer communication or printing.** The original
CAL-03 package and the default renderer have not changed.

Read [the findings and evidence boundaries](../../JPEG_QUALITY_AND_FORMATS.md).
The [machine-readable results](results.json) record 18 baseline encodings and
35 firmware header/setup cases. Image metrics use Pillow's host decoder, not the
firmware's pixel decoder or a physical print.

| Image | Parameters | Bytes | Status |
|---|---|---:|---|
| [Original CAL-03](../calibration/package-v3/python.jpg) | Quality 90, 4:2:0 | 96,490 | Existing prepared file; CAL-03 unprinted |
| [Quality 95 candidate](q95-444-optimized.jpg) | Quality 95, 4:4:4 | 127,471 | Offline header/setup accepted; physical result unknown |
| [Quality 100 candidate](q100-444-optimized.jpg) | Quality 100, 4:4:4 | 151,545 | Offline header/setup accepted; physical result unknown |

All three are baseline JPEGs with optimized Huffman coding and no PhotoFix.
Candidate SHA-256 values:

```text
q95-444-optimized.jpg
21b338cb68592ec8acc999584d990f67b6a74dd0f27d2027a256983aa1693ae8
q100-444-optimized.jpg
50b58d8cc26ba7349e7874861e8c76b16b4b0f5ac6d2962fa0051d970de83944
```

![Channel-range comparison after host JPEG decoding](modulation.png)

The plot measures requested RGB channel range in one-pixel vertical stripe
interiors. A 100% bar is not a claim of pixel-exact reconstruction, isolated dye
activation, or printed contrast. The full report defines the measurement.

## Reproduce

Run from the repository root with Python 3.11 or newer and a dedicated virtual
environment. The recorded run used Python 3.14. Dependencies are separate from
the ordinary printer probe:

```sh
python3 -m venv logs/jpeg-quality-venv
logs/jpeg-quality-venv/bin/python -m pip install -r experiments/jpeg-quality/requirements.txt
logs/jpeg-quality-venv/bin/python experiments/jpeg-quality/compare.py \
  logs/color-firmware-research/G1L1FS2105AR_1.0.7.rbn \
  --output logs/jpeg-quality \
  --plot experiments/jpeg-quality/modulation.png \
  > experiments/jpeg-quality/results.json
logs/jpeg-quality-venv/bin/python -m unittest discover \
  -s experiments/jpeg-quality -p 'test_*.py'
logs/jpeg-quality-venv/bin/python -m unittest discover \
  -s experiments/firmware -p 'test_trace_jpeg.py'
```

The exact privately retained firmware package is required for ARM execution;
the hash is in the report and runner. The seven unit tests need no vendor binary
or printer. The script writes all 18 encodings under the requested local output
directory. Only the two selected candidates are retained here. No script in this
experiment imports a Bluetooth transport, contacts a printer, or sends a job.
