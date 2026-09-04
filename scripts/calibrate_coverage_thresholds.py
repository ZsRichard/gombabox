"""Calibrate the classical coverage detector against hand-made masks.

Example:
    python scripts/calibrate_coverage_thresholds.py \
        --images-dir exported/images --masks-dir exported/masks \
        --output-csv coverage_threshold_results.csv

Image and mask files are paired by filename stem.  Reference masks may contain
0/1 or 0/255 values; every non-zero pixel is treated as mycelium.
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
from core.vision import ImageAnalyzer


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


def index_files(directory: Path) -> dict[str, Path]:
    return {
        path.stem: path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    }


def crop_bounds(width: int, height: int, crop: dict[str, float]) -> tuple[int, int, int, int]:
    left = int(width * crop["left"] / 100.0)
    top = int(height * crop["top"] / 100.0)
    right = width - int(width * crop["right"] / 100.0)
    bottom = height - int(height * crop["bottom"] / 100.0)
    return left, top, right, bottom


def load_pairs(images_dir: Path, masks_dir: Path, crop: dict[str, float]):
    images = index_files(images_dir)
    masks = index_files(masks_dir)
    common_stems = sorted(images.keys() & masks.keys())
    if not common_stems:
        raise ValueError("No image/mask pairs with matching filename stems were found")

    pairs = []
    for stem in common_stems:
        with Image.open(images[stem]) as source:
            image = source.convert("RGB")
        with Image.open(masks[stem]) as source:
            mask = source.convert("L")
        if mask.size != image.size:
            mask = mask.resize(image.size, Image.Resampling.NEAREST)

        bounds = crop_bounds(image.width, image.height, crop)
        pairs.append((
            stem,
            image.crop(bounds),
            np.asarray(mask.crop(bounds)) > 0,
        ))
    return pairs


def evaluate(pairs, brightness: float, saturation: float) -> dict[str, float]:
    coverage_errors = []
    ious = []
    dices = []

    for _, image, reference in pairs:
        prediction = ImageAnalyzer._create_white_mask(
            image,
            brightness_threshold=brightness,
            saturation_threshold=saturation,
        )
        intersection = np.logical_and(prediction, reference).sum()
        union = np.logical_or(prediction, reference).sum()
        prediction_count = prediction.sum()
        reference_count = reference.sum()

        coverage_errors.append(abs(prediction.mean() - reference.mean()) * 100.0)
        ious.append(intersection / union if union else 1.0)
        denominator = prediction_count + reference_count
        dices.append((2.0 * intersection) / denominator if denominator else 1.0)

    return {
        "brightness_threshold": brightness,
        "saturation_threshold": saturation,
        "coverage_mae_pp": float(np.mean(coverage_errors)),
        "mean_iou": float(np.mean(ious)),
        "mean_dice": float(np.mean(dices)),
    }


def parse_crop(value: str | None) -> dict[str, float]:
    if not value:
        return {key: float(number) for key, number in MYCELIUM_ROI_CROP.items()}
    numbers = [float(part.strip()) for part in value.split(",")]
    if len(numbers) != 4 or any(number < 0 or number >= 50 for number in numbers):
        raise ValueError("--crop must be top,left,right,bottom percentages between 0 and 50")
    return dict(zip(("top", "left", "right", "bottom"), numbers))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images-dir", type=Path, required=True)
    parser.add_argument("--masks-dir", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, default=Path("coverage_threshold_results.csv"))
    parser.add_argument(
        "--crop",
        help="ROI crop as top,left,right,bottom percentages; defaults to production values",
    )
    args = parser.parse_args()

    crop = parse_crop(args.crop)
    pairs = load_pairs(args.images_dir, args.masks_dir, crop)
    results = [
        evaluate(pairs, brightness, saturation)
        for brightness in range(120, 181, 5)
        for saturation in np.arange(0.15, 0.401, 0.025)
    ]
    results.sort(key=lambda item: (item["coverage_mae_pp"], -item["mean_iou"]))

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

    print(f"Evaluated {len(results)} settings on {len(pairs)} image/mask pairs")
    print(f"ROI crop: {crop}")
    print("Best settings:")
    for result in results[:10]:
        print(
            f"  V>{result['brightness_threshold']:.0f}, "
            f"S<{result['saturation_threshold']:.3f}: "
            f"MAE={result['coverage_mae_pp']:.2f} pp, "
            f"IoU={result['mean_iou']:.3f}, Dice={result['mean_dice']:.3f}"
        )
    print(f"Full results: {args.output_csv}")


if __name__ == "__main__":
    main()
