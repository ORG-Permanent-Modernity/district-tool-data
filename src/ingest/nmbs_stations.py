"""Fetch NMBS/SNCB railway stations.

Fetches Belgian railway station locations from iRail community API.
Includes station names (multilingual), coordinates, and facilities info.

Source: https://github.com/iRail/stations

Usage:
    python -m src.ingest.nmbs_stations antwerp haringrode
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point

from src.ingest._common import (
    aoi_bbox,
    append_ingest_log,
    load_aoi,
    neighbourhood_path,
)


def ingest_nmbs_stations(city: str, neighbourhood: str) -> None:
    """Fetch NMBS/SNCB stations.

    Args:
        city: City name
        neighbourhood: Neighbourhood name
    """
    started_at = datetime.now(timezone.utc)
    print(f"Ingesting NMBS stations for {city}/{neighbourhood}...")

    # Load AOI for filtering
    aoi = load_aoi(city, neighbourhood)
    bbox = aoi_bbox(city, neighbourhood, buffer_m=5000)  # 5km buffer for nearby stations

    print(f"  Searching within 5km of AOI...")

    # Reproject AOI to WGS84 for Overpass query
    aoi_wgs84 = aoi.to_crs("EPSG:4326")
    minx, miny, maxx, maxy = aoi_wgs84.total_bounds

    # Add 0.1 degree buffer (~10km) for Overpass query
    buffer = 0.1
    query_bbox = (miny - buffer, minx - buffer, maxy + buffer, maxx + buffer)

    # Overpass QL query for railway stations
    overpass_query = f"""[out:json][timeout:60];
(
  node["railway"="station"]({query_bbox[0]},{query_bbox[1]},{query_bbox[2]},{query_bbox[3]});
  node["railway"="halt"]({query_bbox[0]},{query_bbox[1]},{query_bbox[2]},{query_bbox[3]});
);
out;"""

    overpass_url = "https://overpass-api.de/api/interpreter"

    headers = {
        'User-Agent': 'district-tool-data/0.1 (research project; https://github.com/ORG)'
    }

    print(f"  Querying Overpass API for railway stations...")
    response = requests.post(
        overpass_url,
        data={'data': overpass_query},
        headers=headers,
        timeout=120
    )
    response.raise_for_status()
    data = response.json()

    elements = data.get("elements", [])
    print(f"  Received {len(elements)} stations from OSM")

    # Parse stations
    stations = []
    for elem in elements:
        if elem["type"] != "node":
            continue

        tags = elem.get("tags", {})
        stations.append({
            "osm_id": elem["id"],
            "name": tags.get("name", ""),
            "railway_type": tags.get("railway", ""),
            "operator": tags.get("operator", ""),
            "latitude": elem["lat"],
            "longitude": elem["lon"],
        })

    # Create GeoDataFrame
    if len(stations) > 0:
        df = pd.DataFrame(stations)
        geometry = [Point(lon, lat) for lon, lat in zip(df["longitude"], df["latitude"])]
        gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")
    else:
        # Empty GeoDataFrame
        gdf = gpd.GeoDataFrame(
            columns=["osm_id", "name", "railway_type", "operator", "latitude", "longitude", "geometry"],
            crs="EPSG:4326"
        )

    print(f"  Fetched {len(gdf)} stations for Belgium")

    # Reproject to EPSG:31370
    gdf = gdf.to_crs("EPSG:31370")

    # Filter to buffered AOI
    aoi_geom = aoi.union_all()
    buffered_aoi = aoi_geom.buffer(5000)  # 5km

    gdf_filtered = gdf[gdf.intersects(buffered_aoi)].copy()

    print(f"  Kept {len(gdf_filtered)} stations within 5km of AOI")

    if len(gdf_filtered) == 0:
        print("  Warning: No stations found near AOI")

    # Save to raw
    base = neighbourhood_path(city, neighbourhood)
    raw_dir = base / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    output_path = raw_dir / f"nmbs_stations_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.gpkg"

    gdf_filtered.to_file(output_path, driver="GPKG")
    print(f"  Saved to {output_path}")

    # Log
    finished_at = datetime.now(timezone.utc)
    append_ingest_log(
        city=city,
        dataset="nmbs_stations",
        neighbourhood=neighbourhood,
        started_at=started_at,
        finished_at=finished_at,
        status="success",
        output_path=output_path,
        rows_fetched=len(gdf_filtered),
        notes="NMBS/SNCB stations via iRail API, filtered to 5km buffer",
    )

    print(f"\n✓ Done! NMBS stations saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest NMBS stations")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    ingest_nmbs_stations(args.city, args.neighbourhood)
