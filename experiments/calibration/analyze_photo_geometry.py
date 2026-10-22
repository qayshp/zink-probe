"""Offline CAL-02 geometry from manual landmarks; no printer access or image edits.

No physical units or resolution estimates are inferred. Raw photographs are not
distributed. --photo-dir optionally verifies the private originals' hashes/sizes.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

PACKAGE = Path(__file__).resolve().parent / "package-v2"


def projective_map(source, destination):
    rows, values = [], []
    for (x, y), (u, v) in zip(source, destination, strict=True):
        rows.extend(
            [
                [x, y, 1, 0, 0, 0, -u * x, -u * y],
                [0, 0, 0, x, y, 1, -v * x, -v * y],
            ]
        )
        values.extend([u, v])
    return np.r_[np.linalg.solve(rows, values), 1].reshape(3, 3)


def transform(matrix, points):
    points = np.atleast_2d(points)
    homogeneous = np.c_[points, np.ones(len(points))] @ matrix.T
    return homogeneous[:, :2] / homogeneous[:, 2:]


def analyze(photo_dir=None):
    landmarks = json.loads((PACKAGE / "photo-landmarks.json").read_text())
    manifest = json.loads((PACKAGE / "manifest.json").read_text())
    jpeg = PACKAGE / "python.jpg"
    if hashlib.sha256(jpeg.read_bytes()).hexdigest() != landmarks["payload_sha256"]:
        raise ValueError("Payload no longer matches the photographed experiment")
    references = np.array(manifest["reference_centers"], dtype=float)
    width, height = manifest["dimensions"]
    results = []
    for photo in landmarks["photos"]:
        if photo_dir is not None:
            original = photo_dir / photo["name"]
            if hashlib.sha256(original.read_bytes()).hexdigest() != photo["sha256"]:
                raise ValueError(f"Photo hash mismatch: {photo['name']}")
            with Image.open(original) as image:
                if list(image.size) != photo["dimensions"]:
                    raise ValueError(f"Photo dimensions mismatch: {photo['name']}")
        corners = np.array(photo["corner_crosses_abcd"], dtype=float)
        matrix = projective_map(corners, references[:4])
        # Interpolation consistency, not an independent accuracy measurement.
        np.testing.assert_allclose(
            transform(matrix, corners), references[:4], atol=1e-8
        )
        center = transform(matrix, photo["center_cross"])[0]
        error = center - references[4]
        edges, crop = {}, {}
        for edge, points in photo["paper_edges"].items():
            mapped = transform(matrix, points)
            axis = 0 if edge in ("left", "right") else 1
            depths = mapped[:, axis]
            # Source occupies [0,width) x [0,height); subpixel boundary convention.
            if edge == "right":
                depths = width - depths
            elif edge == "bottom":
                depths = height - depths
            edges[edge] = mapped.round(4).tolist()
            crop[edge] = {
                "endpoint_estimates_px": depths.round(4).tolist(),
                "mean_px": round(float(depths.mean()), 4),
            }
        visible_width = width - crop["left"]["mean_px"] - crop["right"]["mean_px"]
        visible_height = height - crop["top"]["mean_px"] - crop["bottom"]["mean_px"]
        results.append(
            {
                "photo": photo["name"],
                "photo_to_source_matrix": matrix.tolist(),
                "withheld_center_source_px": center.round(4).tolist(),
                "withheld_center_error_px": error.round(4).tolist(),
                "withheld_center_error_norm_px": round(float(np.linalg.norm(error)), 4),
                "mapped_paper_edges_source_px": edges,
                "apparent_crop_input_px": crop,
                "approximate_visible_span_input_px": [visible_width, visible_height],
                "approximate_visible_span_percent": [
                    round(100 * visible_width / width, 3),
                    round(100 * visible_height / height, 3),
                ],
            }
        )
    # A simple baseline check avoids attributing JPEG loss to the printer.
    pixels = np.asarray(Image.open(jpeg).convert("RGB"))
    baseline = {}
    for orientation, y in [("vertical", 232), ("horizontal", 362)]:
        patch = pixels[y + 8 : y + 72, 80:144]
        baseline[orientation + "_1px_interior"] = {
            "mean_channel_value": float(patch.mean()),
            "minimum": int(patch.min()),
            "maximum": int(patch.max()),
        }
    return {
        "chart_id": landmarks["chart_id"],
        "payload_sha256": landmarks["payload_sha256"],
        "scope": "Approximate source-coordinate geometry from two photos of one sheet",
        "accuracy_note": "Decimals are arithmetic precision, not calibrated uncertainty. Report crop depths to a few input pixels, not subpixel accuracy.",
        "photos": results,
        "decoded_jpeg_baseline": baseline,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo-dir", type=Path)
    args = parser.parse_args()
    result = analyze(args.photo_dir)
    output = PACKAGE / "photo-geometry.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(output)
