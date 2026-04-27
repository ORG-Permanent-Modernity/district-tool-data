"""Ingest Statbel statistical sectors for a neighbourhood.

Statbel provides statistical sector boundaries as a one-time download (no WFS).
The user must download from the Statbel portal, then this script clips to AOI.

Download location:
    https://statbel.fgov.be/en/open-data/statistical-sectors-2024

Direct download (EPSG:31370, GeoJSON):
    https://statbel.fgov.be/sites/default/files/files/opendata/Statistische%20sectoren/sh_statbel_statistical_sectors_31370_20240101.geojson.zip

The downloaded file should be unzipped and placed in:
    $DATA_ROOT/shared/statbel_sectors_<year>.geojson
    (or .shp, .gpkg - the script checks for multiple formats)

This script:
1. Reads the national dataset from shared/
2. Clips to the neighbourhood AOI (with small buffer for edge cases)
3. Saves to raw/statbel_sectors_<date>.gpkg
4. Logs the ingest run

Usage:
    python -m src.ingest.statbel_sectors antwerp haringrode --source-year 2024
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd

from src.ingest._common import (
    append_ingest_log,
    get_data_root,
    load_aoi,
    neighbourhood_path,
    raw_output_path,
)


def find_source_file(data_root: Path, source_year: int) -> Path:
    """Find the Statbel sectors source file, checking multiple extensions."""
    shared = data_root / "shared"
    extensions = [".gpkg", ".geojson", ".shp"]

    for ext in extensions:
        path = shared / f"statbel_sectors_{source_year}{ext}"
        if path.exists():
            return path

    # Not found - give helpful error
    raise FileNotFoundError(
        f"Statbel sectors not found in {shared}/\n\n"
        f"Expected one of:\n"
        + "\n".join(f"  - statbel_sectors_{source_year}{ext}" for ext in extensions)
        + f"\n\nDownload from:\n"
        f"  https://statbel.fgov.be/en/open-data/statistical-sectors-{source_year}\n\n"
        f"Or direct link (EPSG:31370 GeoJSON):\n"
        f"  https://statbel.fgov.be/sites/default/files/files/opendata/"
        f"Statistische%20sectoren/sh_statbel_statistical_sectors_31370_{source_year}0101.geojson.zip\n\n"
        f"Unzip and rename to: statbel_sectors_{source_year}.geojson"
    )


def ingest_statbel_sectors(
    city: str,
    neighbourhood: str,
    source_year: int = 2024,
) -> Path:
    """Ingest Statbel statistical sectors for a neighbourhood.

    Returns the path to the raw output file.
    """
    started_at = datetime.now(timezone.utc)

    # Source file in shared folder
    data_root = get_data_root()
    source_path = find_source_file(data_root, source_year)

    # Load AOI
    print(f"Loading AOI for {city}/{neighbourhood}...")
    aoi = load_aoi(city, neighbourhood)
    aoi_geom = aoi.union_all()

    # Buffer slightly to catch edge sectors
    aoi_buffered = aoi_geom.buffer(50)

    # Load national sectors
    print(f"Loading national sectors from {source_path}...")
    gdf = gpd.read_file(source_path)
    print(f"  Loaded {len(gdf)} sectors nationally")

    # Ensure EPSG:31370
    if gdf.crs is None or gdf.crs.to_epsg() != 31370:
        print(f"  Reprojecting from {gdf.crs} to EPSG:31370...")
        gdf = gdf.to_crs("EPSG:31370")

    # Clip to AOI (intersects, not strict clip - we want whole sectors)
    print("Selecting sectors intersecting AOI...")
    mask = gdf.geometry.intersects(aoi_buffered)
    gdf_clipped = gdf[mask].copy()
    print(f"  Selected {len(gdf_clipped)} sectors")

    if len(gdf_clipped) == 0:
        raise ValueError(
            "No sectors found intersecting AOI. "
            "Check that the AOI is in EPSG:31370 and within Belgium."
        )

    # Output path
    output_path = raw_output_path(city, neighbourhood, "statbel_sectors")

    # Save
    print(f"Saving to {output_path}...")
    gdf_clipped.to_file(output_path, driver="GPKG")

    # Log
    finished_at = datetime.now(timezone.utc)
    append_ingest_log(
        city=city,
        dataset="statbel_sectors",
        neighbourhood=neighbourhood,
        started_at=started_at,
        finished_at=finished_at,
        status="success",
        output_path=output_path,
        rows_fetched=len(gdf_clipped),
        notes=f"Source: statbel_sectors_{source_year}.gpkg",
    )

    print(f"\nDone! {len(gdf_clipped)} sectors saved to {output_path}")
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest Statbel statistical sectors")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    parser.add_argument(
        "--source-year",
        type=int,
        default=2024,
        help="Year of the Statbel sectors download (default: 2024)",
    )
    args = parser.parse_args()

    ingest_statbel_sectors(args.city, args.neighbourhood, args.source_year)
