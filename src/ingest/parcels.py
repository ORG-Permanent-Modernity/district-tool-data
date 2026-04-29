"""Fetch cadastral parcels from GRB.

Fetches Administratief Perceel (ADP) polygons from the GRB WFS service.
Cadastral parcels define property boundaries and ownership subdivision.

Useful for:
- Development potential analysis
- Green space access (private gardens)
- Land ownership patterns

Usage:
    python -m src.ingest.parcels antwerp haringrode
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import geopandas as gpd

from src.data.catalogue_access import Catalogue
from src.ingest._common import (
    aoi_bbox,
    append_ingest_log,
    neighbourhood_path,
)


def ingest_parcels(city: str, neighbourhood: str) -> None:
    """Fetch cadastral parcels from GRB WFS.

    Args:
        city: City name
        neighbourhood: Neighbourhood name
    """
    started_at = datetime.now(timezone.utc)
    print(f"Ingesting cadastral parcels for {city}/{neighbourhood}...")

    # Get AOI bbox (no buffer - parcels are property boundaries)
    bbox = aoi_bbox(city, neighbourhood, buffer_m=0)
    print(f"  AOI bbox: {bbox}")

    # Fetch from WFS using catalogue
    cat = Catalogue()
    print(f"  Fetching parcels from GRB WFS...")

    gdf = cat.fetch_wfs(
        "grb_gebouwen",
        layer="parcels",
        bbox=bbox,
    )

    print(f"  Fetched {len(gdf)} parcel features")

    if len(gdf) == 0:
        print("  Warning: No parcels returned from WFS")

    # Verify CRS
    if gdf.crs is None or gdf.crs.to_epsg() != 31370:
        print(f"  Warning: CRS is {gdf.crs}, reprojecting to EPSG:31370")
        gdf = gdf.to_crs("EPSG:31370")

    # Save to raw
    base = neighbourhood_path(city, neighbourhood)
    raw_dir = base / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    output_path = raw_dir / f"parcels_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.gpkg"

    gdf.to_file(output_path, driver="GPKG")
    print(f"  Saved to {output_path}")

    # Log
    finished_at = datetime.now(timezone.utc)
    append_ingest_log(
        city=city,
        dataset="parcels",
        neighbourhood=neighbourhood,
        started_at=started_at,
        finished_at=finished_at,
        status="success",
        output_path=output_path,
        rows_fetched=len(gdf),
        notes=f"GRB Administratief Perceel (ADP) via WFS",
    )

    print(f"\n✓ Done! Parcels saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest cadastral parcels")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    ingest_parcels(args.city, args.neighbourhood)
