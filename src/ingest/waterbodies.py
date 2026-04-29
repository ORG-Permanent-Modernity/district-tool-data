"""Fetch water bodies (ponds, lakes) from Watervlakken.

Fetches stagnant water polygons from INBO's Watervlakken dataset.

Data includes:
- Ponds, lakes, reservoirs (Polygon)
- 93,000+ water bodies across Flanders

Source: INBO (Instituut voor Natuur- en Bosonderzoek)
Endpoint: https://gisservices.inbo.be/arcgis/services/Watervlakken/MapServer/WFSServer
CRS: EPSG:31370 (Belgian Lambert 72)

Decisions:
- Fetch with 500m buffer beyond AOI to capture water extending beyond blocks
- Using Watervlakken:Watervlakken layer
- Complements VHA watercourses (flowing water)

Usage:
    python -m src.ingest.waterbodies antwerp haringrode
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import geopandas as gpd
import requests

from src.ingest._common import (
    aoi_bbox,
    append_ingest_log,
    neighbourhood_path,
    raw_output_path,
)


def ingest_waterbodies(city: str, neighbourhood: str) -> None:
    """Fetch water bodies from WFS."""
    started_at = datetime.now(timezone.utc)
    print(f"Ingesting water bodies for {city}/{neighbourhood}...")

    # Get bbox with 500m buffer (water extends beyond blocks)
    bbox = aoi_bbox(city, neighbourhood, buffer_m=500)
    print(f"  AOI bbox (buffered 500m): {bbox}")

    # Fetch from WFS
    wfs_url = "https://gisservices.inbo.be/arcgis/services/Watervlakken/MapServer/WFSServer"
    print(f"  Fetching from {wfs_url}...")

    # Build WFS GetFeature request
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": "Watervlakken:Watervlakken",
        "outputFormat": "GEOJSON",
        "srsName": "EPSG:31370",
        "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]},EPSG:31370",
    }

    response = requests.get(wfs_url, params=params, timeout=120)
    response.raise_for_status()

    # Load GeoJSON
    import json
    geojson = json.loads(response.text)

    # Convert to GeoDataFrame
    waterbodies = gpd.GeoDataFrame.from_features(geojson["features"], crs="EPSG:31370")
    print(f"  Fetched {len(waterbodies)} water body features")

    # Verify CRS
    if waterbodies.crs is None or waterbodies.crs.to_epsg() != 31370:
        print(f"  Reprojecting from {waterbodies.crs} to EPSG:31370...")
        waterbodies = waterbodies.to_crs("EPSG:31370")

    # Save to raw
    output_path = raw_output_path(city, neighbourhood, "waterbodies")

    print(f"  Saving to {output_path}...")
    waterbodies.to_file(output_path, driver="GPKG")

    # Log the ingest
    finished_at = datetime.now(timezone.utc)

    append_ingest_log(
        city=city,
        dataset="waterbodies",
        neighbourhood=neighbourhood,
        started_at=started_at,
        finished_at=finished_at,
        status="success",
        output_path=output_path,
        rows_fetched=len(waterbodies),
        notes="Watervlakken v1.2+ (INBO stagnant water polygons)",
    )

    print(f"\nDone! {len(waterbodies)} water bodies saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest water bodies")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    ingest_waterbodies(args.city, args.neighbourhood)
