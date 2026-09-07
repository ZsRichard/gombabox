"""Add and backfill the camera capture phase column for known grow cycles."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from pathlib import Path


HISTORICAL_PERIODS = [
    ("incubation", "2026-02-24_16-19-05.jpg", "2026-03-13_17-16-40.jpg"),
    ("fruiting", "2026-03-13_17-16-41.jpg", "2026-04-03_15-27-27.jpg"),
    ("incubation", "2026-06-03_11-02-18.jpg", "2026-06-12_11-24-52.jpg"),
    ("fruiting", "2026-06-12_11-24-53.jpg", "2026-07-19_17-01-03.jpg"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()

    database = args.database.resolve()
    if not database.is_file():
        raise FileNotFoundError(database)

    if args.apply and args.backup:
        backup = args.backup.resolve()
        if backup.exists():
            raise FileExistsError(backup)
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(database, backup)
        print(f"Backup: {backup}")

    connection = sqlite3.connect(database)
    try:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(camera_captures)")
        }
        if args.apply:
            connection.execute("BEGIN IMMEDIATE")
            if "phase" not in columns:
                connection.execute(
                    "ALTER TABLE camera_captures ADD COLUMN phase VARCHAR(20)"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS ix_camera_captures_phase "
                "ON camera_captures (phase)"
            )
            for phase, start, end in HISTORICAL_PERIODS:
                connection.execute(
                    f"UPDATE camera_captures SET phase = ? "
                    "WHERE filename >= ? AND filename <= ? "
                    "AND (phase IS NULL OR trim(phase) = '')",
                    (phase, start, end),
                )
            connection.commit()

        has_phase = "phase" in columns or args.apply
        if has_phase:
            print("Phase totals:")
            for row in connection.execute(
                "SELECT coalesce(phase, 'unassigned'), count(*) "
                "FROM camera_captures GROUP BY phase ORDER BY phase"
            ):
                print(f"  {row[0]}: {row[1]}")
        else:
            print("Dry run: phase column is not present yet.")
            for phase, start, end in HISTORICAL_PERIODS:
                count = connection.execute(
                    "SELECT count(*) FROM camera_captures "
                    "WHERE filename >= ? AND filename <= ?",
                    (start, end),
                ).fetchone()[0]
                print(f"  would assign {phase}: {count}")
        print(f"Integrity: {connection.execute('PRAGMA integrity_check').fetchone()[0]}")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
