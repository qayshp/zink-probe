"""Inspect CAL-02 close-up photos offline; no physical resolution/MTF inference.

Sampling rectangles refer to the original photo 4 pixels, not rectified image
pixels. Photo code values are nonlinear and uncalibrated. Private photos are
required to reproduce the spectra; no original photos or camera metadata are published.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

PACKAGE = Path(__file__).resolve().parent / "package-v2"
PHOTO_HASHES = {
    "1-Photo-1.jpg": "4477ab0d65ad04817e4c631e34d00fded5463a78582d14e1e32b3df9f6004488",
    "2-Photo-2.jpg": "3ed238ff1c214d5db4e0df789048859826faba6bc35e09897515810b8a50c6c5",
    "3-Photo-3.jpg": "d4e97ffee63572ffb1a0cca010756c8a6b812b3d3521a62bfb5eae858dec02b0",
    "4-Photo-4.jpg": "902b98b957570fb9ae62ac04c5aa81450bf3a525cf17a1287a6a5d4841d64e76",
}
# orientation, source run width, approximate full-patch extent along variation
# axis, and three interior centers on the perpendicular axis. Units: photo px.
REGIONS = [
    ("vertical", 1, (211, 868), (1660, 1850, 2040)),
    ("vertical", 2, (1045, 1695), (1660, 1850, 2040)),
    ("horizontal", 1, (2585, 3242), (330, 510, 710)),
    ("horizontal", 2, (2585, 3242), (1160, 1330, 1510)),
]


def spectrum(profile):
    x = np.arange(len(profile))
    detrended = profile - np.polyval(np.polyfit(x, profile, 1), x)
    window = np.hanning(len(profile))
    # Zero padding refines peak location numerically, not physical resolution.
    n_fft = 32768
    frequency = np.fft.rfftfreq(n_fft) * len(profile)
    amplitude = 2 * np.abs(np.fft.rfft(detrended * window, n=n_fft)) / window.sum()
    # Broad search, not a search restricted to the expected 20/40-cycle peak.
    candidates = np.flatnonzero((frequency >= 5) & (frequency <= 100))
    peak = candidates[np.argmax(amplitude[candidates])]
    return float(frequency[peak]), float(amplitude[peak])


def analyze(photo_dir):
    payload = PACKAGE / "python.jpg"
    payload_hash = hashlib.sha256(payload.read_bytes()).hexdigest()
    if (
        payload_hash
        != "14e1530787508578341510cbdf827352a604d19b1b14039fc3cf785e26078206"
    ):
        raise ValueError("Payload differs from the physical CAL-02 experiment")
    for name, expected in PHOTO_HASHES.items():
        path = photo_dir / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Photo hash mismatch: {name}")
        with Image.open(path) as image:
            if image.size != (2880, 3840):
                raise ValueError(f"Unexpected dimensions: {name}")
    with Image.open(photo_dir / "4-Photo-4.jpg") as image:
        pixels = np.asarray(image.convert("RGB"), dtype=float)
    proxy = pixels @ np.array([0.2126, 0.7152, 0.0722])
    patches = []
    profiles = {}
    for orientation, run, (start, end), centers in REGIONS:
        measurements = []
        for center in centers:
            if orientation == "vertical":
                box = [start, center - 30, end, center + 30]
                profile = proxy[center - 30 : center + 30, start:end].mean(axis=0)
            else:
                box = [center - 30, start, center + 30, end]
                profile = proxy[start:end, center - 30 : center + 30].mean(axis=1)
            cycles, amplitude = spectrum(profile)
            measurements.append(
                {
                    "photo_sampling_box_exclusive": box,
                    "dominant_cycles_per_approximate_patch": round(cycles, 3),
                    "spectral_half_amplitude_photo_code_values": round(amplitude, 3),
                    "mean_photo_code_value": round(float(profile.mean()), 3),
                }
            )
            if center == centers[1]:
                profiles[f"{orientation}_{run}px"] = profile
        patches.append(
            {
                "orientation": orientation,
                "source_run_width_px": run,
                "source_patch_width_and_height_px": 80,
                "expected_source_cycles": 80 / (2 * run),
                "measurements": measurements,
            }
        )
    return {
        "chart_id": "SELECT-CAL-02",
        "dataset": "Second photo set: four close-ups of the existing sheet",
        "payload_sha256": payload_hash,
        "photo_sha256": PHOTO_HASHES,
        "photo_dimensions": [2880, 3840],
        "sampled_photo": "4-Photo-4.jpg",
        "method": "60-photo-pixel bands averaged perpendicular to pattern variation; linear detrend, Hann window, FFT peak search over 5..100 cycles per approximate patch extent.",
        "signal": "0.2126 R + 0.7152 G + 0.0722 B on encoded JPEG RGB; not linear light, reflectance or calibrated luminance.",
        "limits": "Manual approximate patch spans; no rectification, optical calibration, scale reference or established sensor-relative rotation control. Peak amplitudes include the print/camera/lighting chain. Zero padding adds no physical resolution. Not MTF or printer DPI.",
        "patches": patches,
    }, profiles


def plot(profiles, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, sharey=True)
    for ax, orientation in zip(axes, ["vertical", "horizontal"], strict=True):
        profile = profiles[f"{orientation}_1px"]
        x = np.arange(len(profile)) * 80 / len(profile)
        ax.plot(x, profile, color="#2766a2", linewidth=1.4)
        ax.set_title(f"{orientation.capitalize()} 1-pixel runs, photo 4")
        ax.set_ylabel("Encoded RGB brightness proxy")
        ax.set_xlim(20, 40)
        ax.set_ylim(0, 130)
        ax.grid(alpha=0.25)
    axes[-1].set_xlabel("Approximate input-pixel position across each patch")
    fig.suptitle(
        "Periodic structure survives in both directions; these are uncalibrated photo signals"
    )
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo-dir", type=Path, required=True)
    parser.add_argument("--plot", type=Path)
    args = parser.parse_args()
    result, profiles = analyze(args.photo_dir)
    output = PACKAGE / "closeup-analysis.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    if args.plot:
        plot(profiles, args.plot)
    print(output)
