"""Ingest BWK (Biological Valuation Map) for a neighbourhood.

Fetches habitat polygons from the BWK (Biologische Waarderingskaart) via WFS.
Each polygon has biotope codes and ecological valuation scores.

Usage:
    python -m src.ingest.bwk antwerp haringrode
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


def ingest_bwk(city: str, neighbourhood: str) -> None:
    """Fetch BWK habitat map from WFS."""
    started_at = datetime.now(timezone.utc)
    print(f"Ingesting BWK for {city}/{neighbourhood}...")

    # Get bbox with 200m buffer
    bbox = aoi_bbox(city, neighbourhood, buffer_m=200)
    print(f"  AOI bbox (buffered 200m): {bbox}")

    # Fetch from WFS using catalogue
    cat = Catalogue()
    print("  Fetching from BWK WFS...")

    # BWK:Bwkhab is the main habitat layer
    gdf = cat.fetch_wfs(
        "bwk",
        type_name="BWK:Bwkhab",
        bbox=bbox,
    )
    print(f"  Fetched {len(gdf)} BWK polygons")

    # Verify CRS
    if gdf.crs is None or gdf.crs.to_epsg() != 31370:
        print(f"  Reprojecting from {gdf.crs} to EPSG:31370...")
        gdf = gdf.to_crs("EPSG:31370")

    # Save to raw
    output_path = raw_output_path(city, neighbourhood, "bwk")
    print(f"  Saving to {output_path}...")
    gdf.to_file(output_path, driver="GPKG")

    # Log the ingest
    finished_at = datetime.now(timezone.utc)
    append_ingest_log(
        city=city,
        dataset="bwk",
        neighbourhood=neighbourhood,
        started_at=started_at,
        finished_at=finished_at,
        status="success",
        output_path=output_path,
        rows_fetched=len(gdf),
    )

    print(f"Done! {len(gdf)} BWK polygons saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest BWK biological valuation map")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    ingest_bwk(args.city, args.neighbourhood)
