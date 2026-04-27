"""Clean BWK (Biological Valuation Map) for a neighbourhood.

This script processes BWK habitat polygons:
- Clips to AOI
- Extracts biotope codes and ecological valuation
- Computes polygon area
- Adds stable UUIDs

Decisions:
- Clipped strictly to AOI (not buffered)
- Keep biotope codes (EENH1-EENH8) as arrays
- TAG is the primary classification
- EVAL is the ecological valuation score

BWK biotope codes (EENH1-EENH8):
  Each field contains a biotope code. A polygon can have multiple biotopes.
  Common codes include: 'ha' (lawn), 'hp' (pasture), 'hd' (dune),
  'sf' (shrub), 'kw' (artificial), etc.

EVAL (ecological valuation):
  - 'zeer waardevol' (very valuable)
  - 'biologisch waardevol' (biologically valuable)
  - 'minder waardevol' (less valuable)
  - 'geen' or empty (no valuation)

Usage:
    python -m src.clean.bwk antwerp haringrode
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd

from src.clean._common import CleaningLog, fix_invalid_geometries, stable_uuid
from src.ingest._common import load_aoi, neighbourhood_path


def clean_bwk(city: str, neighbourhood: str) -> CleaningLog:
    """Clean BWK biological valuation map for a neighbourhood.

    Returns:
        CleaningLog with details of what was done.
    """
    now = datetime.now(timezone.utc)
    base = neighbourhood_path(city, neighbourhood)

    # Find raw input
    raw_candidates = sorted(base.glob("raw/bwk_*.gpkg"), reverse=True)
    if not raw_candidates:
        raise FileNotFoundError(f"No raw BWK data found in {base}/raw/")
    raw_path = raw_candidates[0]

    # Output path
    cleaned_path = base / "cleaned" / "bwk.gpkg"

    # Load AOI
    aoi = load_aoi(city, neighbourhood)
    aoi_geom = aoi.union_all()

    # Start cleaning log
    log = CleaningLog(
        dataset="bwk",
        raw_input_path=str(raw_path),
        cleaned_output_path=str(cleaned_path),
        started_at=now,
    )

    # Load raw data
    print(f"Loading raw BWK from {raw_path}...")
    gdf = gpd.read_file(raw_path)
    log.rows_in = len(gdf)
    print(f"  Loaded {len(gdf)} BWK polygons")

    # Fix invalid geometries
    print("Fixing invalid geometries...")
    n_invalid = (~gdf.geometry.is_valid).sum()
    gdf, n_dropped_invalid = fix_invalid_geometries(gdf)
    if n_invalid > 0:
        log.anomalies.append(
            f"{n_invalid} invalid geometries found, {n_dropped_invalid} unfixable and dropped"
        )
        print(f"  Fixed {n_invalid - n_dropped_invalid}, dropped {n_dropped_invalid}")

    # Clip to AOI
    print("Clipping to AOI...")
    before = len(gdf)
    gdf = gdf.clip(aoi_geom)
    # Remove empty geometries after clip
    gdf = gdf[~gdf.geometry.is_empty]
    after = len(gdf)
    n_dropped = before - after
    if n_dropped > 0:
        log.rows_dropped["outside AOI or empty after clip"] = n_dropped
        print(f"  Dropped {n_dropped} polygons outside AOI")

    log.decisions.append("Polygons clipped strictly to AOI")

    # Extract biotope codes
    print("Extracting biotope codes...")
    biotope_cols = [f"EENH{i}" for i in range(1, 9)]
    existing_biotope_cols = [c for c in biotope_cols if c in gdf.columns]

    # Create list of biotopes for each polygon (removing None/empty)
    def get_biotopes(row):
        biotopes = []
        for col in existing_biotope_cols:
            val = row.get(col)
            if val and str(val).strip():
                biotopes.append(str(val).strip())
        return biotopes

    gdf["biotope_codes"] = gdf.apply(get_biotopes, axis=1)
    gdf["primary_biotope"] = gdf["biotope_codes"].apply(lambda x: x[0] if x else None)
    log.columns_added.extend(["biotope_codes", "primary_biotope"])
    log.decisions.append("biotope_codes aggregated from EENH1-EENH8 columns")

    # Biotope distribution
    biotope_counts = {}
    for codes in gdf["biotope_codes"]:
        for code in codes:
            biotope_counts[code] = biotope_counts.get(code, 0) + 1
    print(f"  Top biotopes: {dict(sorted(biotope_counts.items(), key=lambda x: -x[1])[:5])}")

    # Extract classification tag
    if "TAG" in gdf.columns:
        gdf["classification"] = gdf["TAG"]
        log.columns_added.append("classification")
        log.decisions.append("classification from TAG column")

    # Extract ecological valuation
    if "EVAL" in gdf.columns:
        # Normalize valuation
        eval_map = {
            "zeer waardevol": "very_valuable",
            "biologisch waardevol": "valuable",
            "minder waardevol": "less_valuable",
            "complex van biologisch waardevolle en minder waardevolle elementen": "mixed",
        }
        gdf["valuation"] = gdf["EVAL"].str.lower().map(eval_map).fillna("unknown")
        log.columns_added.append("valuation")
        log.decisions.append("valuation normalized from EVAL column")

        # Valuation distribution
        val_counts = gdf["valuation"].value_counts().to_dict()
        print(f"  Valuation distribution: {val_counts}")

    # Compute area
    print("Computing polygon areas...")
    gdf["area_m2"] = gdf.geometry.area
    log.columns_added.append("area_m2")

    # Add stable UUIDs
    print("Adding stable UUIDs...")
    gdf["id"] = [stable_uuid() for _ in range(len(gdf))]

    # Source ID from OIDN
    source_id_col = None
    for col in ["OIDN", "oidn", "ObjectId", "objectId"]:
        if col in gdf.columns:
            source_id_col = col
            break

    if source_id_col:
        gdf["source_id"] = gdf[source_id_col].astype(str)
    else:
        gdf["source_id"] = [f"bwk_{i}" for i in range(len(gdf))]

    log.columns_added.extend(["id", "source_id"])

    # Select final columns
    final_cols = [
        "id",
        "source_id",
        "geometry",
        "primary_biotope",
        "classification",
        "valuation",
        "area_m2",
    ]
    # Keep biotope_codes as JSON-serializable list needs special handling
    # For now, keep just primary_biotope

    gdf = gdf[[c for c in final_cols if c in gdf.columns]]

    # Save
    print(f"Saving to {cleaned_path}...")
    cleaned_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(cleaned_path, driver="GPKG")

    # Finalize log
    log.rows_out = len(gdf)
    log.finished_at = datetime.now(timezone.utc)
    log.save()

    total_area_ha = gdf["area_m2"].sum() / 10000
    print(f"\nDone! {log.rows_in} -> {log.rows_out} BWK polygons ({total_area_ha:.2f} ha)")
    print(f"Cleaning log saved to {cleaned_path}.cleaning_log.yaml")

    return log


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean BWK biological valuation map")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    clean_bwk(args.city, args.neighbourhood)
