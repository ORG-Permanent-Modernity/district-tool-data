"""Fetch VHA (Flemish Hydrography Atlas) water features.

Fetches watercourses from the VMM WFS service.

Data includes:
- Watercourses: rivers, streams, canals (LineString) - VHA:VHAG layer

Source: VMM (Flemish Environment Agency)
Endpoint: https://geo.api.vlaanderen.be/VHAWaterlopen/wfs
CRS: EPSG:31370 (Belgian Lambert 72)

Decisions:
- Fetch with 500m buffer beyond AOI to capture water extending beyond blocks
- Using VHAWaterlopen:VHAG layer (complete watercourses)
- Water bodies (polygons) not found in VHAWaterlopen service - deferred to future work

Usage:
    python -m src.ingest.vha antwerp haringrode
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
    raw_output_path,
)


def ingest_vha(city: str, neighbourhood: str) -> None:
    """Fetch VHA water features from WFS."""
    started_at = datetime.now(timezone.utc)
    print(f"Ingesting VHA for {city}/{neighbourhood}...")

    # Get bbox with 500m buffer (water extends beyond blocks)
    bbox = aoi_bbox(city, neighbourhood, buffer_m=500)
    print(f"  AOI bbox (buffered 500m): {bbox}")

    # Fetch from WFS using catalogue
    cat = Catalogue()

    # Fetch watercourses
    print("  Fetching watercourses from VHA WFS...")
    watercourses = cat.fetch_wfs(
        "vha",
        layer="watercourses",  # Maps to VHAWaterlopen:VHAG
        bbox=bbox,
    )
    print(f"  Fetched {len(watercourses)} watercourse features")

    # Verify CRS
    if watercourses.crs is None or watercourses.crs.to_epsg() != 31370:
        print(f"  Reprojecting from {watercourses.crs} to EPSG:31370...")
        watercourses = watercourses.to_crs("EPSG:31370")

    # Save to raw
    base = neighbourhood_path(city, neighbourhood)
    raw_dir = base / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    output_path = raw_output_path(city, neighbourhood, "vha_watercourses")

    print(f"  Saving to {output_path}...")
    watercourses.to_file(output_path, driver="GPKG")

    # Log the ingest
    finished_at = datetime.now(timezone.utc)

    append_ingest_log(
        city=city,
        dataset="vha",
        neighbourhood=neighbourhood,
        started_at=started_at,
        finished_at=finished_at,
        status="success",
        output_path=output_path,
        rows_fetched=len(watercourses),
        notes="Watercourses only (VHAWaterlopen:VHAG). Water bodies (polygons) not yet available.",
    )

    print(f"\nDone! {len(watercourses)} watercourses saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest VHA water features")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    ingest_vha(args.city, args.neighbourhood)
