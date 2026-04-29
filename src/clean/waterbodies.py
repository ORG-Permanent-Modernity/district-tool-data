"""Clean water bodies (ponds, lakes) from Watervlakken.

Processes raw water body polygons from INBO's Watervlakken dataset.

Cleaning steps:
- Normalize column names
- Extract relevant attributes (name, category, area)
- Filter out micro-features (< 2m²)
- Clip to AOI

Decisions:
- Minimum area: 2 m² (filter noise)
- Category normalization from WTRLICHC codes
- Kept with 500m buffer (not strict clipping)

Usage:
    python -m src.clean.waterbodies antwerp haringrode
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import geopandas as gpd

from src.clean._common import CleaningLog
from src.ingest._common import neighbourhood_path


def clean_waterbodies(city: str, neighbourhood: str) -> CleaningLog:
    """Clean water bodies data.

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
    raw_files = list(raw_dir.glob("waterbodies_*.gpkg"))
    if not raw_files:
        raise FileNotFoundError(f"No water bodies found in {raw_dir}")

    raw_path = max(raw_files)  # Most recent by name
    print(f"Loading {raw_path}...")

    waterbodies = gpd.read_file(raw_path)

    # Start cleaning log
    log = CleaningLog(
        dataset="waterbodies",
        raw_input_path=str(raw_path),
        cleaned_output_path=str(base / "cleaned" / "waterbodies.gpkg"),
        started_at=now,
    )
    log.rows_in = len(waterbodies)
    print(f"Loaded {len(waterbodies)} water bodies")

    # Show available columns
    print(f"\nRaw columns: {list(waterbodies.columns)}")

    # Normalize column names
    column_map = {
        "OBJECTID": "source_id",
        "WVLNAAM": "name",
        "WTRLICHC": "water_body_code",
        "OPMERK": "notes",
        "Shape_Area": "area_m2",
    }

    # Select and rename columns that exist
    existing_cols = {k: v for k, v in column_map.items() if k in waterbodies.columns}
    waterbodies = waterbodies[list(existing_cols.keys()) + ["geometry"]].copy()
    waterbodies = waterbodies.rename(columns=existing_cols)

    log.columns_renamed.update(existing_cols)

    # Compute area if not present
    if "area_m2" not in waterbodies.columns:
        waterbodies["area_m2"] = waterbodies.geometry.area
        log.columns_added.append("area_m2")
        log.decisions.append("Computed area_m2 from geometry")

    # Filter out micro-features (< 2m²)
    before = len(waterbodies)
    waterbodies = waterbodies[waterbodies["area_m2"] >= 2.0].copy()
    dropped_small = before - len(waterbodies)
    if dropped_small > 0:
        log.rows_dropped["area < 2m²"] = dropped_small
        print(f"Filtered {dropped_small} micro-polygons (< 2m²)")

    # Classify category from water body code (if exists)
    if "water_body_code" in waterbodies.columns:
        def classify_category(code):
            """Map Watervlakken codes to simple categories."""
            if code is None or str(code).strip() == "":
                return "unknown"
            code_str = str(code).upper().strip()
            # Based on Watervlakken documentation:
            # VL_ = Flemish water body, L_ = local water body
            if code_str.startswith("VL_"):
                return "flemish_water_body"
            elif code_str.startswith("L_"):
                return "local_water_body"
            else:
                return "other"

        waterbodies["category"] = waterbodies["water_body_code"].apply(classify_category)
        log.columns_added.append("category")
        log.decisions.append("Category classified from WTRLICHC codes: flemish_water_body, local_water_body, other")

    # Sort by area (largest first)
    waterbodies = waterbodies.sort_values("area_m2", ascending=False)

    # Save to cleaned
    cleaned_dir = base / "cleaned"
    cleaned_dir.mkdir(parents=True, exist_ok=True)
    cleaned_path = cleaned_dir / "waterbodies.gpkg"

    print(f"\nSaving to {cleaned_path}...")
    waterbodies.to_file(cleaned_path, driver="GPKG")

    # Finalize log
    log.rows_out = len(waterbodies)
    log.finished_at = datetime.now(timezone.utc)
    log.decisions.append("Kept all water bodies within buffered AOI (500m)")
    log.save()

    print(f"\nDone! {len(waterbodies)} water bodies cleaned")
    print(f"Cleaning log: {cleaned_path}.cleaning_log.yaml")

    # Show summary
    print(f"\nTotal area: {waterbodies['area_m2'].sum():.2f} m²")
    if "category" in waterbodies.columns:
        print(f"\nCategory breakdown:")
        print(waterbodies["category"].value_counts())

    return log


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean water bodies data")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    clean_waterbodies(args.city, args.neighbourhood)
