"""Clean VHA (Flemish Hydrography Atlas) watercourse data.

Processes raw VHA watercourses fetched from WFS.

Cleaning steps:
- Normalize column names
- Classify watercourse categories (river, stream, canal, etc.)
- Filter out micro-features (< 10m length)
- Extract relevant attributes (name, category, manager)

Decisions:
- Keep all watercourses within buffered AOI (clipping done at review stage)
- Minimum length: 10m (filter noise from micro-segments)
- Category normalization: map VHA codes to simple river/stream/canal/ditch

Usage:
    python -m src.clean.vha antwerp haringrode
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import geopandas as gpd

from src.clean._common import CleaningLog
from src.ingest._common import neighbourhood_path


def clean_vha(city: str, neighbourhood: str) -> CleaningLog:
    """Clean VHA watercourse data.

    Args:
        city: City name
        neighbourhood: Neighbourhood name

    Returns:
        CleaningLog with details of what was done.
    """
    now = datetime.now(timezone.utc)
    base = neighbourhood_path(city, neighbourhood)

    # Find the most recent raw file
    raw_dir = base / "raw"
    raw_files = list(raw_dir.glob("vha_watercourses_*.gpkg"))
    if not raw_files:
        raise FileNotFoundError(f"No VHA watercourses found in {raw_dir}")

    raw_path = max(raw_files)  # Most recent by name
    print(f"Loading {raw_path}...")

    watercourses = gpd.read_file(raw_path)

    # Start cleaning log
    log = CleaningLog(
        dataset="vha",
        raw_input_path=str(raw_path),
        cleaned_output_path=str(base / "cleaned" / "vha_watercourses.gpkg"),
        started_at=now,
    )
    log.rows_in = len(watercourses)
    print(f"Loaded {len(watercourses)} watercourses")

    # Show available columns
    print(f"\nRaw columns: {list(watercourses.columns)}")

    # Normalize column names
    column_map = {
        "OIDN": "source_id",
        "NAAM": "name",
        "CATEGORIE": "category_code",
        "BEHEER": "manager",
        "LENGTE": "length_m",
    }

    # Select and rename columns that exist
    existing_cols = {k: v for k, v in column_map.items() if k in watercourses.columns}
    watercourses = watercourses[list(existing_cols.keys()) + ["geometry"]].copy()
    watercourses = watercourses.rename(columns=existing_cols)

    log.columns_renamed.update(existing_cols)

    # Filter out micro-features (< 10m)
    if "length_m" in watercourses.columns:
        before = len(watercourses)
        watercourses = watercourses[watercourses["length_m"] >= 10].copy()
        dropped_short = before - len(watercourses)
        if dropped_short > 0:
            log.rows_dropped["length < 10m"] = dropped_short
            print(f"Filtered {dropped_short} micro-segments (< 10m)")

    # Classify categories (if category_code exists)
    if "category_code" in watercourses.columns:
        def classify_category(code):
            """Map VHA category codes to simple categories."""
            if code is None:
                return "unknown"
            code_str = str(code).upper()
            # Based on VHA documentation:
            # 1 = river, 2 = stream, 3 = canal, 4 = ditch
            category_map = {
                "1": "river",
                "2": "stream",
                "3": "canal",
                "4": "ditch",
            }
            return category_map.get(code_str, "unknown")

        watercourses["category"] = watercourses["category_code"].apply(classify_category)
        log.columns_added.append("category")
        log.decisions.append("Category normalized from VHA codes: 1=river, 2=stream, 3=canal, 4=ditch")

    # Add computed length if not present
    if "length_m" not in watercourses.columns:
        watercourses["length_m"] = watercourses.geometry.length
        log.columns_added.append("length_m")
        log.decisions.append("Computed length_m from geometry")

    # Sort by name for consistency
    if "name" in watercourses.columns:
        watercourses = watercourses.sort_values("name", na_position="last")

    # Save to cleaned
    cleaned_dir = base / "cleaned"
    cleaned_dir.mkdir(parents=True, exist_ok=True)
    cleaned_path = cleaned_dir / "vha_watercourses.gpkg"

    print(f"\nSaving to {cleaned_path}...")
    watercourses.to_file(cleaned_path, driver="GPKG")

    # Finalize log
    log.rows_out = len(watercourses)
    log.finished_at = datetime.now(timezone.utc)
    log.decisions.append("Kept all watercourses within buffered AOI (500m)")
    log.save()

    print(f"\nDone! {len(watercourses)} watercourses cleaned")
    print(f"Cleaning log: {cleaned_path}.cleaning_log.yaml")

    # Show category breakdown
    if "category" in watercourses.columns:
        print(f"\nCategory breakdown:")
        print(watercourses["category"].value_counts())

    return log


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean VHA watercourse data")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    clean_vha(args.city, args.neighbourhood)
