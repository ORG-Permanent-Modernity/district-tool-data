"""Fetch flood-prone areas (overstromingsgevoelige gebieden).

Fetches the watertoets advisory map showing flood-prone areas from VMM/Waterinfo WFS.

Data includes:
- Flood risk polygons (fluvial, pluvial, coastal)
- Risk categories and classifications

Source: VMM / Waterinfo
Endpoint: https://vha.waterinfo.be/arcgis/services/advieskaart_watertoets_WFS/MapServer/WFSServer
CRS: EPSG:31370 (Belgian Lambert 72)

Decisions:
- Fetch with 200m buffer beyond AOI
- Using advieskaart_watertoets_WFS:Advieskaart layer

Usage:
    python -m src.ingest.flood_zones antwerp haringrode
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


def ingest_flood_zones(city: str, neighbourhood: str) -> None:
    """Fetch flood zone data from WFS."""
    started_at = datetime.now(timezone.utc)
    print(f"Ingesting flood zones for {city}/{neighbourhood}...")

    # Get bbox with 200m buffer
    bbox = aoi_bbox(city, neighbourhood, buffer_m=200)
    print(f"  AOI bbox (buffered 200m): {bbox}")

    # Fetch from WFS
    wfs_url = "https://vha.waterinfo.be/arcgis/services/advieskaart_watertoets_WFS/MapServer/WFSServer"
    print(f"  Fetching from {wfs_url}...")

    # Build WFS GetFeature request
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": "advieskaart_watertoets_WFS:Advieskaart",
        "outputFormat": "GEOJSON",
        "srsName": "EPSG:31370",
        "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]},EPSG:31370",
    }

    response = requests.get(wfs_url, params=params, timeout=120)
    response.raise_for_status()

    # Load GeoJSON
    import json
    from io import StringIO
    geojson = json.loads(response.text)

    # Convert to GeoDataFrame
    flood_zones = gpd.GeoDataFrame.from_features(geojson["features"], crs="EPSG:31370")
    print(f"  Fetched {len(flood_zones)} flood zone features")

    # Verify CRS
    if flood_zones.crs is None or flood_zones.crs.to_epsg() != 31370:
        print(f"  Reprojecting from {flood_zones.crs} to EPSG:31370...")
        flood_zones = flood_zones.to_crs("EPSG:31370")

    # Save to raw
    output_path = raw_output_path(city, neighbourhood, "flood_zones")

    print(f"  Saving to {output_path}...")
    flood_zones.to_file(output_path, driver="GPKG")

    # Log the ingest
    finished_at = datetime.now(timezone.utc)

    append_ingest_log(
        city=city,
        dataset="flood_zones",
        neighbourhood=neighbourhood,
        started_at=started_at,
        finished_at=finished_at,
        status="success",
        output_path=output_path,
        rows_fetched=len(flood_zones),
        notes="Watertoets advisory map (advieskaart)",
    )

    print(f"\nDone! {len(flood_zones)} flood zones saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest flood zone data")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    ingest_flood_zones(args.city, args.neighbourhood)
