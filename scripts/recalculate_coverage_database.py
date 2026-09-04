"""Recalculate stored mycelium coverage values from the source images.

The command is a dry run unless ``--apply`` is supplied.  Images are matched to
``camera_captures.filename`` by their basename; ambiguous duplicate basenames
are rejected so that a value can never be written from the wrong photograph.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.vision import ImageAnalyzer  # noqa: E402


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def image_index(image_directories: list[Path]) -> tuple[dict[str, Path], dict[str, list[Path]]]:
    candidates: dict[str, list[Path]] = defaultdict(list)
    for directory in image_directories:
        if not directory.is_dir():
            raise FileNotFoundError(f"Image directory does not exist: {directory}")
        for path in directory.iterdir():
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                candidates[path.name].append(path)

    ambiguous = {name: paths for name, paths in candidates.items() if len(paths) > 1}
    unique = {name: paths[0] for name, paths in candidates.items() if len(paths) == 1}
    return unique, ambiguous


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--images-dir", required=True, action="append", type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the calculated values. Without this option no data is changed.",
    )
    args = parser.parse_args()

    database = args.database.resolve()
    if not database.is_file():
        raise FileNotFoundError(f"Database does not exist: {database}")

    images, ambiguous = image_index([path.resolve() for path in args.images_dir])
    if ambiguous:
        examples = ", ".join(sorted(ambiguous)[:5])
        raise RuntimeError(f"Ambiguous image basenames ({len(ambiguous)}): {examples}")

    connection = sqlite3.connect(database)
    try:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(camera_captures)")
        }
        required = {"id", "filename", "analysis_result"}
        if not required.issubset(columns):
            raise RuntimeError(
                "camera_captures is missing required columns: "
                + ", ".join(sorted(required - columns))
            )

        rows = connection.execute(
            "SELECT id, filename, analysis_result FROM camera_captures ORDER BY id"
        ).fetchall()
        matched = [row for row in rows if row[1] in images]
        unmatched = [row for row in rows if row[1] not in images]

        print(f"Database rows: {len(rows)}")
        print(f"Available unique images: {len(images)}")
        print(f"Matched database rows: {len(matched)}")
        print(f"Unmatched database rows (left unchanged): {len(unmatched)}")

        results: list[tuple[str, int, str, str]] = []
        total = len(matched)
        for index, (capture_id, filename, old_value) in enumerate(matched, start=1):
            coverage = ImageAnalyzer.calculate_mycelium_coverage(str(images[filename]))
            new_value = f"{coverage:.2f}%"
            results.append((new_value, capture_id, filename, old_value))
            if index == 1 or index % 50 == 0 or index == total:
                print(f"Calculated {index}/{total}: {filename} -> {new_value}", flush=True)

        changed = [row for row in results if row[0] != row[3]]
        print(f"Values that differ: {len(changed)}")
        if results:
            numeric = [float(value.rstrip("%")) for value, *_ in results]
            print(
                f"New matched range: {min(numeric):.2f}% .. {max(numeric):.2f}%"
            )

        if args.apply:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                "UPDATE camera_captures SET analysis_result = ? WHERE id = ?",
                [(value, capture_id) for value, capture_id, _, _ in results],
            )
            connection.commit()
            print(f"Committed {len(results)} row updates.")
        else:
            print("Dry run only; database was not modified.")

        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        print(f"SQLite integrity_check: {integrity}")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
