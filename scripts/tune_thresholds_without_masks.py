"""Rank brightness/saturation thresholds without hand-labelled masks.

This is a heuristic calibration.  It favours a low initial false-positive
rate, a stable late plateau, few downward jumps and a useful growth range.
It does not replace validation against hand-labelled reference masks.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.constants import MYCELIUM_ROI_CROP


def crop_bounds(width: int, height: int, crop: dict[str, float]) -> tuple[int, int, int, int]:
    return (
        int(width * crop["left"] / 100.0),
        int(height * crop["top"] / 100.0),
        width - int(width * crop["right"] / 100.0),
        height - int(height * crop["bottom"] / 100.0),
    )


def image_histogram(path: Path, crop: dict[str, float], analysis_width: int) -> np.ndarray:
    with Image.open(path) as source:
        image = source.convert("RGB")
    image = image.crop(crop_bounds(image.width, image.height, crop))
    if image.width > analysis_width:
        height = max(1, round(image.height * analysis_width / image.width))
        image = image.resize((analysis_width, height), Image.Resampling.BILINEAR)

    rgb = np.asarray(image, dtype=np.float32)
    red, green, blue = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    gray = np.clip(((red + green + blue) / 3.0).astype(np.int16), 0, 255)
    maximum = np.maximum.reduce((red, green, blue))
    minimum = np.minimum.reduce((red, green, blue))
    saturation = np.divide(
        maximum - minimum,
        maximum,
        out=np.zeros_like(maximum),
        where=maximum > 0,
    )
    saturation_bin = np.clip((saturation * 200).astype(np.int16), 0, 200)
    histogram = np.zeros((256, 201), dtype=np.int64)
    np.add.at(histogram, (gray.ravel(), saturation_bin.ravel()), 1)
    return histogram


def coverage_series(
    histograms: list[np.ndarray], brightness: int, saturation: float
) -> np.ndarray:
    saturation_bin = min(200, max(0, int(saturation * 200)))
    return np.asarray([
        histogram[brightness + 1 :, :saturation_bin].sum() / histogram.sum() * 100.0
        for histogram in histograms
    ])


def score_series(values: np.ndarray, expected_initial: float, plateau_size: int) -> dict[str, float]:
    deltas = np.diff(values)
    negative_deltas = np.maximum(-deltas, 0.0)
    plateau = values[-min(plateau_size, len(values)) :]
    initial_error = abs(float(values[0]) - expected_initial)
    late_std = float(np.std(plateau))
    downward_motion = float(np.mean(negative_deltas)) if len(negative_deltas) else 0.0
    growth_range = float(values[-1] - values[0])
    insufficient_range = max(0.0, 60.0 - growth_range)
    heuristic_score = (
        initial_error
        + (2.0 * late_std)
        + (8.0 * downward_motion)
        + (0.15 * insufficient_range)
    )
    return {
        "start_percent": float(values[0]),
        "end_percent": float(values[-1]),
        "growth_range_pp": growth_range,
        "late_std_pp": late_std,
        "mean_downward_motion_pp": downward_motion,
        "drops_over_1pp": int(np.sum(deltas < -1.0)),
        "heuristic_score": heuristic_score,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("images_dir", type=Path)
    parser.add_argument("--output-csv", type=Path, default=Path("unsupervised_threshold_results.csv"))
    parser.add_argument("--expected-initial", type=float, default=5.0)
    parser.add_argument("--plateau-size", type=int, default=24)
    parser.add_argument("--analysis-width", type=int, default=640)
    args = parser.parse_args()

    files = sorted(args.images_dir.glob("*.jpg"))
    if len(files) < 2:
        raise ValueError("At least two JPG images are required")
    crop = {key: float(value) for key, value in MYCELIUM_ROI_CROP.items()}
    histograms = [image_histogram(path, crop, args.analysis_width) for path in files]

    rows = []
    for brightness in range(120, 181, 5):
        for saturation in np.arange(0.15, 0.401, 0.025):
            values = coverage_series(histograms, brightness, float(saturation))
            rows.append({
                "brightness_threshold": brightness,
                "saturation_threshold": round(float(saturation), 3),
                **score_series(values, args.expected_initial, args.plateau_size),
            })
    rows.sort(key=lambda row: row["heuristic_score"])

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"Analysed {len(files)} images and {len(rows)} threshold pairs")
    print("Top heuristic candidates:")
    for row in rows[:12]:
        print(
            f"  V>{row['brightness_threshold']}, S<{row['saturation_threshold']:.3f} | "
            f"{row['start_percent']:.2f}% -> {row['end_percent']:.2f}% | "
            f"late SD {row['late_std_pp']:.2f} pp | drops {row['drops_over_1pp']} | "
            f"score {row['heuristic_score']:.2f}"
        )
    print(f"Full results: {args.output_csv}")


if __name__ == "__main__":
    main()
