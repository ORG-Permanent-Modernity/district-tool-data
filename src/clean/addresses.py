"""Clean addresses for a neighbourhood.

This script processes Adressenregister addresses:
- Clips to AOI (strict, no buffer for point data)
- Extracts key address fields
- Optionally joins to nearest building (for building_id)
- Adds stable UUIDs

Decisions:
- Points clipped strictly to AOI (no buffer needed)
- Joined to nearest building footprint for building_id reference
- Keep full address, street name, municipality, postcode

Usage:
    python -m src.clean.addresses antwerp haringrode [--join-buildings]
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

from src.clean._common import CleaningLog, fix_invalid_geometries, stable_uuid
from src.ingest._common import load_aoi, neighbourhood_path


def clean_addresses(city: str, neighbourhood: str, join_buildings: bool = False) -> CleaningLog:
    """Clean addresses for a neighbourhood.

    Args:
        city: City name
        neighbourhood: Neighbourhood name
        join_buildings: If True, join each address to nearest building

    Returns:
        CleaningLog with details of what was done.
    """
    now = datetime.now(timezone.utc)
    base = neighbourhood_path(city, neighbourhood)

    # Find raw input
    raw_candidates = sorted(base.glob("raw/addresses_*.gpkg"), reverse=True)
    if not raw_candidates:
        raise FileNotFoundError(f"No raw addresses data found in {base}/raw/")
    raw_path = raw_candidates[0]

    # Output path
    cleaned_path = base / "cleaned" / "addresses.gpkg"

    # Load AOI
    aoi = load_aoi(city, neighbourhood)
    aoi_geom = aoi.union_all()

    # Start cleaning log
    log = CleaningLog(
        dataset="addresses",
        raw_input_path=str(raw_path),
        cleaned_output_path=str(cleaned_path),
        started_at=now,
    )

    # Load raw data
    print(f"Loading raw addresses from {raw_path}...")
    gdf = gpd.read_file(raw_path)
    log.rows_in = len(gdf)
    print(f"  Loaded {len(gdf)} addresses")

    # Fix invalid geometries
    print("Fixing invalid geometries...")
    n_invalid = (~gdf.geometry.is_valid).sum()
    gdf, n_dropped_invalid = fix_invalid_geometries(gdf)
    if n_invalid > 0:
        log.anomalies.append(
            f"{n_invalid} invalid geometries found, {n_dropped_invalid} unfixable and dropped"
        )
        print(f"  Fixed {n_invalid - n_dropped_invalid}, dropped {n_dropped_invalid}")

    # Clip to AOI (strict, no buffer for point data)
    print("Clipping to AOI...")
    before = len(gdf)
    gdf = gdf[gdf.intersects(aoi_geom)]
    after = len(gdf)
    n_dropped = before - after
    if n_dropped > 0:
        log.rows_dropped["outside AOI"] = n_dropped
        print(f"  Dropped {n_dropped} addresses outside AOI")

    # Extract key fields
    print("Extracting address fields...")

    # Column mapping based on typical Adressenregister schema
    # Columns seen: VolledigAdres, Straatnaam, Gemeentenaam, Postcode (from PostinfoObjectId)
    gdf["full_address"] = gdf.get("VolledigAdres", gdf.get("volledigAdres", ""))
    gdf["street_name"] = gdf.get("Straatnaam", gdf.get("straatnaam", ""))
    gdf["municipality"] = gdf.get("Gemeentenaam", gdf.get("gemeentenaam", ""))

    # Huisnummer might be in a separate field or parse from full address
    if "Huisnummer" in gdf.columns:
        gdf["house_number"] = gdf["Huisnummer"].astype(str)
    elif "huisnummer" in gdf.columns:
        gdf["house_number"] = gdf["huisnummer"].astype(str)
    else:
        gdf["house_number"] = None

    log.columns_added.extend(["full_address", "street_name", "municipality", "house_number"])
    log.decisions.append("Address fields extracted from Adressenregister schema")

    # Get source_id from ObjectId or OIDN
    source_id_col = None
    for col in ["ObjectId", "objectId", "OIDN", "oidn", "Id_1"]:
        if col in gdf.columns:
            source_id_col = col
            break

    if source_id_col:
        gdf["source_id"] = gdf[source_id_col].astype(str)
    else:
        gdf["source_id"] = [f"addr_{i}" for i in range(len(gdf))]

    # Join to buildings (optional)
    if join_buildings:
        buildings_path = base / "reviewed" / "buildings.gpkg"
        if buildings_path.exists():
            print("Joining addresses to nearest buildings...")
            buildings = gpd.read_file(buildings_path)
            # For each address, find nearest building
            gdf["building_id"] = None
            # Use spatial join with nearest (requires geopandas >= 0.10)
            try:
                joined = gpd.sjoin_nearest(
                    gdf, buildings[["id", "geometry"]], how="left", distance_col="dist_to_building"
                )
                gdf["building_id"] = joined["id_right"]
                log.columns_added.append("building_id")
                log.decisions.append("building_id joined from nearest building footprint")
                n_matched = gdf["building_id"].notna().sum()
                print(f"  Matched {n_matched} addresses to buildings")
            except Exception as e:
                print(f"  Warning: building join failed: {e}")
                log.anomalies.append(f"building join failed: {e}")
        else:
            print("  Warning: buildings.gpkg not found, skipping building join")
            log.anomalies.append("buildings.gpkg not found, building_id not populated")
    else:
        log.decisions.append("building_id not populated (--join-buildings not specified)")

    # Add stable UUIDs
    print("Adding stable UUIDs...")
    gdf["id"] = [stable_uuid() for _ in range(len(gdf))]
    log.columns_added.extend(["id", "source_id"])

    # Select final columns
    final_cols = [
        "id",
        "source_id",
        "geometry",
        "full_address",
        "street_name",
        "house_number",
        "municipality",
    ]
    if "building_id" in gdf.columns:
        final_cols.append("building_id")
    if "dist_to_building" in gdf.columns:
        final_cols.append("dist_to_building")

    gdf = gdf[[c for c in final_cols if c in gdf.columns]]

    # Save
    print(f"Saving to {cleaned_path}...")
    cleaned_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(cleaned_path, driver="GPKG")

    # Finalize log
    log.rows_out = len(gdf)
    log.finished_at = datetime.now(timezone.utc)
    log.save()

    print(f"\nDone! {log.rows_in} -> {log.rows_out} addresses")
    print(f"Cleaning log saved to {cleaned_path}.cleaning_log.yaml")

    return log


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean addresses from Adressenregister")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    parser.add_argument(
        "--join-buildings",
        action="store_true",
        help="Join each address to nearest building (slower)",
    )
    args = parser.parse_args()

    clean_addresses(args.city, args.neighbourhood, join_buildings=args.join_buildings)
