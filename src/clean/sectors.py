"""Clean Statbel statistical sectors for a neighbourhood.

This script processes statistical sector boundaries:
- Keeps sectors that intersect AOI (not clipped - we want whole sectors)
- Normalizes column names to schema
- Adds stable UUIDs

Decisions:
- Sectors are NOT clipped to AOI boundary (they're statistical units)
- Population will be joined later from statbel_population dataset
- Sector codes (CD_SECTOR) are unique national identifiers

Schema output:
- id: stable UUID
- source_id: sector code (CD_SECTOR)
- name_nl: Dutch name
- name_fr: French name
- municipality_nis: NIS code of municipality
- area_m2: official area from Statbel

Usage:
    python -m src.clean.sectors antwerp haringrode
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import geopandas as gpd

from src.clean._common import CleaningLog, fix_invalid_geometries, stable_uuid
from src.ingest._common import load_aoi, neighbourhood_path


def clean_sectors(city: str, neighbourhood: str) -> CleaningLog:
    """Clean statistical sectors for a neighbourhood.

    Returns the CleaningLog with details of what was done.
    """
    now = datetime.now(timezone.utc)
    base = neighbourhood_path(city, neighbourhood)

    # Find raw input
    raw_candidates = sorted(base.glob("raw/statbel_sectors_*.gpkg"), reverse=True)
    if not raw_candidates:
        raise FileNotFoundError(f"No raw Statbel sectors found in {base}/raw/")
    raw_path = raw_candidates[0]

    # Output path
    cleaned_path = base / "cleaned" / "sectors.gpkg"

    # Load AOI for reference
    aoi = load_aoi(city, neighbourhood)
    aoi_geom = aoi.union_all()

    # Start cleaning log
    log = CleaningLog(
        dataset="sectors",
        raw_input_path=str(raw_path),
        cleaned_output_path=str(cleaned_path),
        started_at=now,
    )

    # Load raw data
    print(f"Loading raw sectors from {raw_path}...")
    gdf = gpd.read_file(raw_path)
    log.rows_in = len(gdf)
    print(f"  Loaded {len(gdf)} sectors")

    # Fix invalid geometries
    print("Fixing invalid geometries...")
    n_invalid = (~gdf.geometry.is_valid).sum()
    gdf, n_dropped_invalid = fix_invalid_geometries(gdf)
    if n_invalid > 0:
        log.anomalies.append(
            f"{n_invalid} invalid geometries found, {n_dropped_invalid} unfixable and dropped"
        )
        print(f"  Fixed {n_invalid - n_dropped_invalid}, dropped {n_dropped_invalid}")

    # Print available columns for debugging
    print(f"  Available columns: {list(gdf.columns)}")

    # Normalize column names (Statbel uses various naming conventions)
    # Common fields: cd_sector (or CD_SECTOR), tx_sector_descr_nl, tx_sector_descr_fr
    col_map = {}

    # Find sector code column
    for candidate in ["cd_sector", "CD_SECTOR", "CDSECTOR", "sector_id"]:
        if candidate in gdf.columns:
            col_map[candidate] = "source_id"
            break

    # Find name columns
    for candidate in ["tx_sector_descr_nl", "TX_SECTOR_DESCR_NL", "T_SEC_NL", "sector_nl"]:
        if candidate in gdf.columns:
            col_map[candidate] = "name_nl"
            break

    for candidate in ["tx_sector_descr_fr", "TX_SECTOR_DESCR_FR", "T_SEC_FR", "sector_fr"]:
        if candidate in gdf.columns:
            col_map[candidate] = "name_fr"
            break

    # Find municipality NIS code
    for candidate in ["cd_munty_refnis", "CD_MUNTY_REFNIS", "CNIS5_2023", "nis_code"]:
        if candidate in gdf.columns:
            col_map[candidate] = "municipality_nis"
            break

    print(f"  Column mapping: {col_map}")

    # Rename columns
    gdf = gdf.rename(columns=col_map)

    # Add stable UUIDs
    print("Adding stable UUIDs...")
    gdf["id"] = [stable_uuid() for _ in range(len(gdf))]
    log.columns_added.append("id")

    # Compute area if not present
    if "area_m2" not in gdf.columns:
        print("Computing area...")
        gdf["area_m2"] = gdf.geometry.area
        log.columns_added.append("area_m2")
        log.decisions.append("area_m2 computed from geometry")

    # Ensure source_id is string
    if "source_id" in gdf.columns:
        gdf["source_id"] = gdf["source_id"].astype(str)
    else:
        # Create from index if no sector code found
        gdf["source_id"] = [str(i) for i in range(len(gdf))]
        log.anomalies.append("No sector code column found, using index as source_id")

    # Ensure name columns exist
    if "name_nl" not in gdf.columns:
        gdf["name_nl"] = None
    if "name_fr" not in gdf.columns:
        gdf["name_fr"] = None
    if "municipality_nis" not in gdf.columns:
        gdf["municipality_nis"] = None

    log.decisions.append("Sectors kept as whole polygons (not clipped to AOI)")
    log.decisions.append("Population to be joined from statbel_population dataset")

    # Select final columns
    final_cols = [
        "id",
        "source_id",
        "geometry",
        "name_nl",
        "name_fr",
        "municipality_nis",
        "area_m2",
    ]
    gdf = gdf[final_cols]

    # Save
    print(f"Saving to {cleaned_path}...")
    cleaned_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(cleaned_path, driver="GPKG")

    # Finalize log
    log.rows_out = len(gdf)
    log.finished_at = datetime.now(timezone.utc)
    log.save()

    print(f"\nDone! {log.rows_in} -> {log.rows_out} sectors")
    print(f"Cleaning log saved to {cleaned_path}.cleaning_log.yaml")

    return log


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean Statbel statistical sectors")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    clean_sectors(args.city, args.neighbourhood)
