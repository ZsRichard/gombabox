"""Create a lightweight audit of incubation image series and stored coverage values."""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.vision import ImageAnalyzer


PERCENT_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def parse_percentage(value: object) -> float | None:
    if value is None:
        return None
    match = PERCENT_RE.search(str(value))
    return float(match.group()) if match else None


def load_stored_values(database: Path) -> dict[str, float]:
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT filename, analysis_result FROM camera_captures"
        ).fetchall()
    return {
        filename: percentage
        for filename, raw_value in rows
        if (percentage := parse_percentage(raw_value)) is not None
    }


def evenly_spaced(items: list[Path], count: int) -> list[Path]:
    if len(items) <= count:
        return items
    indices = [round(index * (len(items) - 1) / (count - 1)) for index in range(count)]
    return [items[index] for index in indices]


def create_contact_sheet(
    files: list[Path], stored: dict[str, float], destination: Path, columns: int = 4
) -> None:
    samples = evenly_spaced(files, 16)
    tile_width, image_height, label_height = 480, 270, 42
    rows = (len(samples) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_width, rows * (image_height + label_height)), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=18)

    for index, path in enumerate(samples):
        with Image.open(path) as source:
            source_image = source.convert("RGB")
            improved = ImageAnalyzer.calculate_mycelium_coverage_from_image(
                source_image, preprocessing="roi"
            )
            image = ImageOps.fit(source_image, (tile_width, image_height))
        x = (index % columns) * tile_width
        y = (index // columns) * (image_height + label_height)
        sheet.paste(image, (x, y))
        percentage = stored.get(path.name)
        stored_label = f"stored {percentage:.2f}%" if percentage is not None else "no DB value"
        suffix = f" | {stored_label} | ROI {improved:.2f}%"
        draw.text((x + 8, y + image_height + 8), path.stem + suffix, fill="black", font=font)

    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, quality=92)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("datasets", nargs="+", type=Path)
    args = parser.parse_args()

    stored = load_stored_values(args.database)
    for index, dataset in enumerate(args.datasets, start=1):
        files = sorted(dataset.glob("*.jpg"))
        destination = args.output / f"incubation_{index}_contact_sheet.jpg"
        create_contact_sheet(files, stored, destination)
        matched = sum(path.name in stored for path in files)
        print(f"{dataset}: {len(files)} images, {matched} stored values -> {destination}")


if __name__ == "__main__":
    main()
