"""Fetch greenspace data from Stad Antwerpen portal.

Fetches public parks and green areas from Antwerp's ArcGIS portal.

Two datasets:
1. Parks - City-managed parks and important public green zones
2. Green and Water Classification - All public green/water areas classified
   by accessibility and type

Source: https://portaal-stadantwerpen.opendata.arcgis.com/

Usage:
    python -m src.ingest.greenspace antwerp haringrode
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import geopandas as gpd
import pandas as pd
import requests

from src.ingest._common import (
    aoi_bbox,
    append_ingest_log,
    load_aoi,
    neighbourhood_path,
)


def ingest_greenspace(city: str, neighbourhood: str) -> None:
    """Fetch greenspace data from Antwerp portal.

    Args:
        city: City name
        neighbourhood: Neighbourhood name
    """
    started_at = datetime.now(timezone.utc)
    print(f"Ingesting greenspace data for {city}/{neighbourhood}...")

    # Load AOI for clipping
    aoi = load_aoi(city, neighbourhood)
    bbox = aoi_bbox(city, neighbourhood, buffer_m=0)

    print(f"  AOI bbox: {bbox}")

    # Antwerp ArcGIS portal GeoJSON export URLs
    datasets = {
        "parks": "https://portaal-stadantwerpen.opendata.arcgis.com/datasets/park.geojson",
        "green_water": "https://portaal-stadantwerpen.opendata.arcgis.com/datasets/groen-en-water-hoofdindeling.geojson",
    }

    all_features = []
    total_fetched = 0

    for dataset_name, geojson_url in datasets.items():
        print(f"\n  Fetching {dataset_name}...")

        try:
            # Download GeoJSON first with headers
            headers = {
                'User-Agent': 'district-tool-data/0.1 (research project)'
            }
            response = requests.get(geojson_url, headers=headers, timeout=180)
            response.raise_for_status()

            # Parse with GeoPandas
            import io
            gdf_full = gpd.read_file(io.BytesIO(response.content))

            if len(gdf_full) == 0:
                print(f"    No features in dataset")
                continue

            # Reproject if needed
            if gdf_full.crs is None or gdf_full.crs.to_epsg() != 31370:
                print(f"    Reprojecting from {gdf_full.crs} to EPSG:31370")
                gdf_full = gdf_full.to_crs("EPSG:31370")

            # Clip to AOI
            gdf_clipped = gdf_full[gdf_full.intersects(aoi.union_all())]

            if len(gdf_clipped) > 0:
                gdf_clipped["source_dataset"] = dataset_name
                all_features.append(gdf_clipped)
                total_fetched += len(gdf_clipped)
                print(f"    Fetched {len(gdf_clipped)} features (from {len(gdf_full)} total)")
            else:
                print(f"    No features within AOI")

        except Exception as e:
            print(f"    Failed: {e}")
            continue

    if len(all_features) == 0:
        print("\n  Warning: No greenspace data fetched")
        # Create empty GeoDataFrame
        gdf_combined = gpd.GeoDataFrame(
            columns=["geometry", "source_dataset"],
            crs="EPSG:31370"
        )
    else:
        # Combine datasets
        gdf_combined = gpd.GeoDataFrame(
            pd.concat(all_features, ignore_index=True),
            crs="EPSG:31370"
        )

    print(f"\n  Total features: {total_fetched}")

    # Save to raw
    base = neighbourhood_path(city, neighbourhood)
    raw_dir = base / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    output_path = raw_dir / f"greenspace_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.gpkg"

    gdf_combined.to_file(output_path, driver="GPKG")
    print(f"  Saved to {output_path}")

    # Log
    finished_at = datetime.now(timezone.utc)
    append_ingest_log(
        city=city,
        dataset="greenspace",
        neighbourhood=neighbourhood,
        started_at=started_at,
        finished_at=finished_at,
        status="success" if total_fetched > 0 else "partial",
        output_path=output_path,
        rows_fetched=total_fetched,
        notes="Antwerp parks + green/water classification via ArcGIS FeatureServer",
    )

    print(f"\n✓ Done! Greenspace data saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest greenspace data")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    ingest_greenspace(args.city, args.neighbourhood)
