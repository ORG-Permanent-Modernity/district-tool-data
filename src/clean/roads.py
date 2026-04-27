"""Clean Wegenregister roads for a neighbourhood.

This script processes Wegenregister road segments:
- Normalizes morfologischeWegklasse to road_class
- Extracts street name (prefers right side, falls back to left)
- Computes segment length
- Adds stable UUIDs
- Keeps buffer in cleaned output (routing needs context)

Decisions:
- Road class mapping from morfologischeWegklasse (see mapping below)
- No speed limit data in WFS - set to null
- Direction set to 'both' (Wegenregister doesn't expose this in WFS)
- Roads kept with buffer (not clipped to strict AOI) for routing context

road_class mapping:
  autosnelweg → highway
  weg met gescheiden rijbanen → arterial
  weg bestaande uit één rijbaan → local
  wandel- of fietsweg → cycleway
  voetgangerszone → pedestrian
  rotonde, ventweg, op/afrit, aardeweg, tramweg, parking → service

Usage:
    python -m src.clean.roads antwerp haringrode
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd

from src.clean._common import CleaningLog, fix_invalid_geometries, stable_uuid
from src.ingest._common import load_aoi, neighbourhood_path


# Mapping from morfologischeWegklasse to normalized road_class
ROAD_CLASS_MAP = {
    "autosnelweg": "highway",
    "weg met gescheiden rijbanen die geen autosnelweg is": "arterial",
    "weg bestaande uit één rijbaan": "local",
    "wandel- of fietsweg, niet toegankelijk voor andere voertuigen": "cycleway",
    "voetgangerszone": "pedestrian",
    "rotonde": "local",
    "ventweg": "service",
    "op- of afrit, behorende tot een gelijkgrondse verbinding": "service",
    "op- of afrit, behorende tot een niet-gelijkgrondse verbinding": "service",
    "aardeweg": "service",
    "tramweg, niet toegankelijk voor andere voertuigen": "service",
    "in- of uitrit van een parking": "service",
}


def clean_roads(city: str, neighbourhood: str) -> CleaningLog:
    """Clean roads for a neighbourhood.

    Returns the CleaningLog with details of what was done.
    """
    now = datetime.now(timezone.utc)
    base = neighbourhood_path(city, neighbourhood)

    # Find raw input
    raw_candidates = sorted(base.glob("raw/wegenregister_*.gpkg"), reverse=True)
    if not raw_candidates:
        raise FileNotFoundError(f"No raw Wegenregister data found in {base}/raw/")
    raw_path = raw_candidates[0]

    # Output path
    cleaned_path = base / "cleaned" / "roads.gpkg"

    # Load AOI (for reference, but we keep buffer for roads)
    aoi = load_aoi(city, neighbourhood)

    # Start cleaning log
    log = CleaningLog(
        dataset="roads",
        raw_input_path=str(raw_path),
        cleaned_output_path=str(cleaned_path),
        started_at=now,
    )

    # Load raw data
    print(f"Loading raw roads from {raw_path}...")
    gdf = gpd.read_file(raw_path)
    log.rows_in = len(gdf)
    print(f"  Loaded {len(gdf)} features")

    # Fix invalid geometries
    print("Fixing invalid geometries...")
    n_invalid = (~gdf.geometry.is_valid).sum()
    gdf, n_dropped_invalid = fix_invalid_geometries(gdf)
    if n_invalid > 0:
        log.anomalies.append(
            f"{n_invalid} invalid geometries found, {n_dropped_invalid} unfixable and dropped"
        )
        print(f"  Fixed {n_invalid - n_dropped_invalid}, dropped {n_dropped_invalid}")

    # Normalize road class
    print("Normalizing road class...")
    gdf["road_class"] = gdf["morfologischeWegklasse"].map(ROAD_CLASS_MAP)

    # Check for unmapped values
    unmapped = gdf[gdf["road_class"].isna()]["morfologischeWegklasse"].unique()
    if len(unmapped) > 0:
        gdf["road_class"] = gdf["road_class"].fillna("service")
        log.anomalies.append(f"Unmapped road classes defaulted to 'service': {list(unmapped)}")
        print(f"  Warning: unmapped classes defaulted to 'service': {unmapped}")

    log.columns_added.append("road_class")
    log.decisions.append("road_class normalized from morfologischeWegklasse")

    # Road class distribution
    class_counts = gdf["road_class"].value_counts().to_dict()
    print(f"  Road class distribution: {class_counts}")

    # Extract street name (prefer right side, fall back to left)
    print("Extracting street names...")
    gdf["name"] = gdf["rechterstraatnaam"].fillna(gdf["linkerstraatnaam"])
    n_named = gdf["name"].notna().sum()
    log.columns_added.append("name")
    log.decisions.append("Street name from rechterstraatnaam, fallback to linkerstraatnaam")
    print(f"  {n_named} segments with names, {len(gdf) - n_named} unnamed")

    # Speed limit - not available in WFS, set null
    gdf["speed_kmh"] = None
    log.columns_added.append("speed_kmh")
    log.decisions.append("speed_kmh set to null (not available in WFS)")

    # Direction - WFS doesn't expose this, default to 'both'
    gdf["direction"] = "both"
    log.columns_added.append("direction")
    log.decisions.append("direction set to 'both' (WFS doesn't expose directionality)")

    # Compute length
    print("Computing segment lengths...")
    gdf["length_m"] = gdf.geometry.length
    log.columns_added.append("length_m")

    # Add stable UUIDs
    print("Adding stable UUIDs...")
    gdf["id"] = [stable_uuid() for _ in range(len(gdf))]
    gdf["source_id"] = gdf["objectId"].astype(str)
    log.columns_added.extend(["id", "source_id"])

    # Note that we keep the buffer (not clipping to strict AOI)
    log.decisions.append("Roads kept with 200m buffer (routing needs context beyond AOI)")

    # Select final columns
    final_cols = [
        "id",
        "source_id",
        "geometry",
        "road_class",
        "speed_kmh",
        "direction",
        "name",
        "length_m",
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

    print(f"\nDone! {log.rows_in} -> {log.rows_out} road segments")
    print(f"Cleaning log saved to {cleaned_path}.cleaning_log.yaml")

    return log


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean Wegenregister roads")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    clean_roads(args.city, args.neighbourhood)
