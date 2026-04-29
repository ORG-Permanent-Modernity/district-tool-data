"""Fetch strategic noise maps as raster tiles.

Fetches noise exposure rasters (Lden, Lnight) from Departement Omgeving WMS service.

Data includes:
- Road traffic noise (Lden, Lnight)
- Rail noise (Lden, Lnight)
- Industry noise (Lden, Lnight)

Source: Departement Omgeving
Endpoint: https://geo.api.vlaanderen.be/geluid/wms
CRS: EPSG:31370 (Belgian Lambert 72)

Decisions:
- Fetch as GeoTIFF rasters via WMS GetMap
- Resolution: 5m (standard for noise mapping in Flanders)
- Fetch AOI + 200m buffer to avoid edge effects
- Separate rasters for each source type

Usage:
    python -m src.ingest.noise_maps antwerp haringrode
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import rasterio
import requests
from rasterio.io import MemoryFile

from src.ingest._common import (
    aoi_bbox,
    append_ingest_log,
    neighbourhood_path,
)


def ingest_noise_maps(city: str, neighbourhood: str) -> None:
    """Fetch noise maps from WMS as GeoTIFF rasters.

    Args:
        city: City name
        neighbourhood: Neighbourhood name
    """
    started_at = datetime.now(timezone.utc)
    print(f"Ingesting noise maps for {city}/{neighbourhood}...")

    # Get bbox with 200m buffer
    bbox = aoi_bbox(city, neighbourhood, buffer_m=200)
    print(f"  AOI bbox (buffered 200m): {bbox}")

    # Calculate dimensions for 5m resolution
    width = int((bbox[2] - bbox[0]) / 5)
    height = int((bbox[3] - bbox[1]) / 5)
    print(f"  Raster dimensions: {width} x {height} pixels (5m resolution)")

    # WMS endpoint
    wms_url = "https://geo.api.vlaanderen.be/geluid/wms"

    # Noise layers to fetch
    # Based on EU Environmental Noise Directive layers
    layers = {
        "road_lden": "geluidsbelasting:Lden_wegverkeer",
        "road_lnight": "geluidsbelasting:Lnight_wegverkeer",
        "rail_lden": "geluidsbelasting:Lden_spoorwegverkeer",
        "rail_lnight": "geluidsbelasting:Lnight_spoorwegverkeer",
        "industry_lden": "geluidsbelasting:Lden_industrie",
        "industry_lnight": "geluidsbelasting:Lnight_industrie",
    }

    # Output directory
    base = neighbourhood_path(city, neighbourhood)
    raw_dir = base / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    successful_layers = []

    for layer_name, wms_layer in layers.items():
        print(f"\n  Fetching {layer_name}...")

        # WMS GetMap request
        params = {
            "SERVICE": "WMS",
            "VERSION": "1.3.0",
            "REQUEST": "GetMap",
            "LAYERS": wms_layer,
            "CRS": "EPSG:31370",
            "BBOX": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
            "WIDTH": width,
            "HEIGHT": height,
            "FORMAT": "image/geotiff",
            "TRANSPARENT": "FALSE",
        }

        try:
            response = requests.get(wms_url, params=params, timeout=120)
            response.raise_for_status()

            # Check if response is actually a GeoTIFF
            if response.headers.get("Content-Type", "").startswith("image/"):
                # Save to file
                output_path = raw_dir / f"noise_{layer_name}_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.tif"

                # Write raster
                with MemoryFile(response.content) as memfile:
                    with memfile.open() as src:
                        # Read and save with proper metadata
                        profile = src.profile
                        profile.update(
                            driver="GTiff",
                            compress="lzw",
                            tiled=True,
                        )

                        with rasterio.open(output_path, "w", **profile) as dst:
                            dst.write(src.read())
                            dst.update_tags(
                                layer=wms_layer,
                                source="Departement Omgeving WMS",
                                fetched_at=started_at.isoformat(),
                            )

                print(f"    Saved to {output_path}")
                successful_layers.append(layer_name)
            else:
                print(f"    ⚠ Layer not available or returned non-image response")

        except Exception as e:
            print(f"    ⚠ Failed: {e}")
            continue

    # Log the ingest
    finished_at = datetime.now(timezone.utc)

    if successful_layers:
        append_ingest_log(
            city=city,
            dataset="noise_maps",
            neighbourhood=neighbourhood,
            started_at=started_at,
            finished_at=finished_at,
            status="success",
            output_path=raw_dir / "noise_*.tif",
            tiles_fetched=len(successful_layers),
            notes=f"Fetched {len(successful_layers)} noise layers: {', '.join(successful_layers)}",
        )

        print(f"\n✓ Done! Fetched {len(successful_layers)} noise map layers")
    else:
        print(f"\n✗ No noise layers successfully fetched")
        append_ingest_log(
            city=city,
            dataset="noise_maps",
            neighbourhood=neighbourhood,
            started_at=started_at,
            finished_at=finished_at,
            status="failed",
            output_path=raw_dir / "noise_*.tif",
            tiles_fetched=0,
            notes="No layers successfully fetched from WMS",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest noise maps from WMS")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    ingest_noise_maps(args.city, args.neighbourhood)
