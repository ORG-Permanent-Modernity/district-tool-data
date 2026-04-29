"""Fetch building construction years from OpenStreetMap.

Queries Overpass API for buildings with 'building:year' or 'start_date' tags
within the neighbourhood AOI.

OSM building age data is sparse and crowd-sourced, but can complement
other sources where available.

Usage:
    python -m src.ingest.osm_building_age antwerp haringrode
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import geopandas as gpd
import requests

from src.ingest._common import append_ingest_log, neighbourhood_path


def fetch_osm_building_ages(city: str, neighbourhood: str) -> None:
    """Fetch building ages from OpenStreetMap.

    Args:
        city: City name
        neighbourhood: Neighbourhood name

    Returns:
        IngestLog with fetch details
    """
    base = neighbourhood_path(city, neighbourhood)

    # Load AOI to get bounding box
    aoi_path = base / "aoi.gpkg"
    if not aoi_path.exists():
        raise FileNotFoundError(f"AOI not found at {aoi_path}")

    aoi = gpd.read_file(aoi_path)
    bounds = aoi.total_bounds  # (minx, miny, maxx, maxy) in EPSG:31370

    # Reproject bounds to EPSG:4326 for Overpass API
    aoi_wgs84 = aoi.to_crs("EPSG:4326")
    minx, miny, maxx, maxy = aoi_wgs84.total_bounds

    print(f"Querying Overpass API for buildings in {city}/{neighbourhood}...")
    print(f"  Bounding box (WGS84): {miny:.5f},{minx:.5f},{maxy:.5f},{maxx:.5f}")

    # Overpass QL query for buildings with construction year
    overpass_query = f"""[out:json][timeout:60];
(
  way["building"]["start_date"]({miny},{minx},{maxy},{maxx});
  way["building"]["building:year"]({miny},{minx},{maxy},{maxx});
  relation["building"]["start_date"]({miny},{minx},{maxy},{maxx});
  relation["building"]["building:year"]({miny},{minx},{maxy},{maxx});
);
out geom;"""

    overpass_url = "https://overpass-api.de/api/interpreter"

    try:
        # User-Agent header required by Overpass API usage policy
        headers = {
            'User-Agent': 'district-tool-data/0.1 (research project; https://github.com/ORG)'
        }
        response = requests.post(
            overpass_url,
            data={'data': overpass_query},
            headers=headers,
            timeout=120
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        print(f"  Error querying Overpass API: {e}")
        raise

    elements = data.get("elements", [])
    print(f"  Received {len(elements)} OSM elements with construction year tags")

    if len(elements) == 0:
        print("  No buildings with construction year found in OSM for this area")
        # Still create empty file for consistency
        features = []
    else:
        # Parse features
        features = []
        for elem in elements:
            if elem["type"] not in ["way", "relation"]:
                continue

            # Extract construction year from tags
            tags = elem.get("tags", {})
            construction_year = None

            # Try building:year first (more specific)
            if "building:year" in tags:
                construction_year = tags["building:year"]
            elif "start_date" in tags:
                # start_date can be YYYY or YYYY-MM-DD
                construction_year = tags["start_date"][:4]

            if construction_year is None:
                continue

            # Try to parse as integer year
            try:
                year = int(construction_year)
                if year < 1000 or year > 2030:
                    continue  # Invalid year
            except ValueError:
                continue  # Can't parse year

            # Build geometry from nodes
            if "geometry" not in elem:
                continue

            coords = [(node["lon"], node["lat"]) for node in elem["geometry"]]

            if len(coords) < 3:
                continue  # Need at least 3 points for a polygon

            # Close polygon if not already closed
            if coords[0] != coords[-1]:
                coords.append(coords[0])

            from shapely.geometry import Polygon
            try:
                geom = Polygon(coords)
            except Exception:
                continue  # Invalid geometry

            features.append({
                "osm_id": elem.get("id"),
                "osm_type": elem["type"],
                "construction_year": year,
                "building_type": tags.get("building", "yes"),
                "geometry": geom
            })

        print(f"  Parsed {len(features)} valid buildings with construction years")

    # Create GeoDataFrame
    if len(features) > 0:
        gdf = gpd.GeoDataFrame(features, crs="EPSG:4326")
        # Reproject to EPSG:31370
        gdf = gdf.to_crs("EPSG:31370")
    else:
        # Empty GeoDataFrame with correct schema
        from shapely.geometry import Polygon
        gdf = gpd.GeoDataFrame(
            {
                "osm_id": [],
                "osm_type": [],
                "construction_year": [],
                "building_type": [],
                "geometry": []
            },
            crs="EPSG:31370"
        )

    # Save to raw
    raw_dir = base / "raw"
    raw_dir.mkdir(exist_ok=True)
    output_path = raw_dir / "osm_building_age.gpkg"

    gdf.to_file(output_path, driver="GPKG")
    print(f"  Saved {len(gdf)} features to {output_path}")

    # Log
    from datetime import datetime, timezone
    finished_at = datetime.now(timezone.utc)
    started_at = finished_at  # Quick operation, no need to track separately

    append_ingest_log(
        city=city,
        neighbourhood=neighbourhood,
        dataset="osm_building_age",
        started_at=started_at,
        finished_at=finished_at,
        status="success",
        output_path=output_path,
        rows_fetched=len(gdf),
        notes=f"OSM Overpass API query for buildings with construction year tags"
    )

    print(f"\nDone! OSM building age data saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch building ages from OSM")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    fetch_osm_building_ages(args.city, args.neighbourhood)
