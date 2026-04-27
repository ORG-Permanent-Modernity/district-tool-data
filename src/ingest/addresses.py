"""Ingest addresses from Adressenregister for a neighbourhood.

Fetches address points from the Flemish address register (Adressenregister)
via WFS. Each address is a geocoded point with street name and municipality.

Usage:
    python -m src.ingest.addresses antwerp haringrode
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import geopandas as gpd

from src.data.catalogue_access import Catalogue
from src.ingest._common import (
    aoi_bbox,
    append_ingest_log,
    raw_output_path,
)


def ingest_addresses(city: str, neighbourhood: str) -> None:
    """Fetch addresses from Adressenregister WFS."""
    started_at = datetime.now(timezone.utc)
    print(f"Ingesting addresses for {city}/{neighbourhood}...")

    # Get bbox (no buffer needed - addresses are point features inside AOI)
    bbox = aoi_bbox(city, neighbourhood, buffer_m=0)
    print(f"  AOI bbox: {bbox}")

    # Fetch from WFS using catalogue
    cat = Catalogue()
    print("  Fetching from Adressenregister WFS...")

    # The catalogue knows the layer name
    gdf = cat.fetch_wfs(
        "adressenregister",
        layer="addresses",  # maps to Adressenregister:Adres
        bbox=bbox,
    )
    print(f"  Fetched {len(gdf)} addresses")

    # Verify CRS
    if gdf.crs is None or gdf.crs.to_epsg() != 31370:
        print(f"  Reprojecting from {gdf.crs} to EPSG:31370...")
        gdf = gdf.to_crs("EPSG:31370")

    # Handle duplicate column names (case-insensitive)
    # WFS returns both 'id' and 'Id' which conflict in GPKG
    cols = gdf.columns.tolist()
    seen = {}
    new_cols = []
    for col in cols:
        lower = col.lower()
        if lower in seen:
            # Rename duplicate
            new_name = f"{col}_{seen[lower]}"
            new_cols.append(new_name)
            seen[lower] += 1
        else:
            new_cols.append(col)
            seen[lower] = 1
    if new_cols != cols:
        print(f"  Renaming duplicate columns: {[c for c, n in zip(cols, new_cols) if c != n]}")
        gdf.columns = new_cols

    # Save to raw
    output_path = raw_output_path(city, neighbourhood, "addresses")
    print(f"  Saving to {output_path}...")
    gdf.to_file(output_path, driver="GPKG")

    # Log the ingest
    finished_at = datetime.now(timezone.utc)
    append_ingest_log(
        city=city,
        dataset="addresses",
        neighbourhood=neighbourhood,
        started_at=started_at,
        finished_at=finished_at,
        status="success",
        output_path=output_path,
        rows_fetched=len(gdf),
    )

    print(f"Done! {len(gdf)} addresses saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest addresses from Adressenregister")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    ingest_addresses(args.city, args.neighbourhood)
