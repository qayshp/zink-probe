"""Rough scale-pen consistency check; explicitly not coplanar metrology.

Photo coordinates are manual picks of tick ends and the paper's long edge
nearest the pen. The three ticks fit a 1D projectivity on the pen's line. Using
it on the separate, lower paper plane is an approximation with unknown bias.
"""

import hashlib
import json
from pathlib import Path

import numpy as np

PACKAGE = Path(__file__).resolve().parent / "package-v2"
PHOTOS = [
    {
        "name": "1-Photo-1.jpg",
        "sha256": "e5e71483f450bbd6c181881f54d7bb9872a0a8f15506be42b916a13a41d1bb5a",
        "tick_x_for_labels_0_10_20": [964, 643, 310],
        "nearby_paper_edge_endpoint_x": [101, 963],
    },
    {
        "name": "2-Photo-2.jpg",
        "sha256": "4d4e2ebe3aa073029fa4cb1b7de991be7dc33a6ff20980fa518718454c2001db",
        "tick_x_for_labels_0_10_20": [1220, 760, 309],
        "nearby_paper_edge_endpoint_x": [22, 1215],
    },
]


def label_map(tick_x):
    x = np.asarray(tick_x, dtype=float)
    labels = np.array([0, 10, 20], dtype=float)
    return np.linalg.solve(np.c_[x, np.ones(3), -labels * x], labels)


def map_x(coefficients, x):
    a, b, c = coefficients
    x = np.asarray(x, dtype=float)
    return (a * x + b) / (c * x + 1)


def analyze():
    measurements = []
    for photo in PHOTOS:
        coefficients = label_map(photo["tick_x_for_labels_0_10_20"])
        np.testing.assert_allclose(
            map_x(coefficients, photo["tick_x_for_labels_0_10_20"]),
            [0, 10, 20],
            atol=1e-10,
        )
        labels = map_x(coefficients, photo["nearby_paper_edge_endpoint_x"])
        measurements.append(
            {
                **photo,
                "photo_dimensions": [1280, 960],
                "coefficients_a_b_c": coefficients.tolist(),
                "apparent_edge_endpoint_labels": labels.tolist(),
                "apparent_length_mm": float(abs(labels[1] - labels[0]) * 1000 / 300),
            }
        )
    payload_hash = hashlib.sha256((PACKAGE / "python.jpg").read_bytes()).hexdigest()
    return {
        "chart_id": "SELECT-CAL-02",
        "payload_sha256": payload_hash,
        "scale_interpretation": "Visible marking read as metre scale 1:300; one labelled unit corresponds to 1000/300 mm on the pen.",
        "method": "Manual x-coordinate picks; label=(a*x+b)/(c*x+1) fitted to 0/10/20. Approximate transfer to paper edge nearest pen.",
        "limitations": "Raised scale and paper are different planes; strongly oblique capture, unknown height, alignment, lens distortion and scale manufacturing accuracy. No calibrated uncertainty. Decimal output is calculation precision only. Do not use to refine crop or printer DPI.",
        "measurements": measurements,
    }


if __name__ == "__main__":
    output = PACKAGE / "scale-pen-analysis.json"
    output.write_text(json.dumps(analyze(), indent=2) + "\n")
    print(output)
