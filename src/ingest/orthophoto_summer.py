"""Ingest summer orthophoto (RGB and CIR) for a neighbourhood.

Fetches summer orthophoto tiles from the Digitaal Vlaanderen WMS service.
Both RGB and CIR (Color-Infrared) bands are fetched to enable NDVI computation.

WMS Endpoint: https://geo.api.vlaanderen.be/OMZ/wms
Layers:
  - OMZRGB21VL: RGB color, 2021, 40cm resolution
  - OMZNIR21VL: Color-infrared, 2021, 40cm resolution

The CIR image has bands: NIR, Red, Green (false color composite)

Usage:
    python -m src.ingest.orthophoto_summer antwerp haringrode
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from io import BytesIO

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from owslib.wms import WebMapService
from PIL import Image

from src.ingest._common import (
    aoi_bbox,
    append_ingest_log,
    neighbourhood_path,
    raw_output_path,
)


WMS_URL = "https://geo.api.vlaanderen.be/OMZ/wms"
RGB_LAYER = "OMZRGB21VL"
CIR_LAYER = "OMZNIR21VL"
RESOLUTION_M = 0.4  # 40cm
MAX_TILE_SIZE = 4096  # Max pixels per request


def fetch_wms_tile(
    wms: WebMapService,
    layer: str,
    bbox: tuple[float, float, float, float],
    width: int,
    height: int,
) -> np.ndarray:
    """Fetch a single WMS tile and return as numpy array."""
    response = wms.getmap(
        layers=[layer],
        srs="EPSG:31370",
        bbox=bbox,
        size=(width, height),
        format="image/png",
    )

    # Read PNG into numpy array
    img = Image.open(BytesIO(response.read()))
    return np.array(img)


def fetch_orthophoto(
    city: str,
    neighbourhood: str,
    layer: str,
    output_suffix: str,
    buffer_m: float = 50,
) -> Path:
    """Fetch orthophoto layer for the AOI.

    Returns path to the saved GeoTIFF.
    """
    started_at = datetime.now(timezone.utc)

    # Get AOI bounds with buffer
    minx, miny, maxx, maxy = aoi_bbox(city, neighbourhood, buffer_m=buffer_m)

    # Calculate output dimensions
    width_m = maxx - minx
    height_m = maxy - miny
    width_px = int(width_m / RESOLUTION_M)
    height_px = int(height_m / RESOLUTION_M)

    print(f"Fetching {layer} for {city}/{neighbourhood}...")
    print(f"  Bounds: {minx:.0f}, {miny:.0f}, {maxx:.0f}, {maxy:.0f}")
    print(f"  Size: {width_px} x {height_px} pixels ({width_m:.0f} x {height_m:.0f} m)")

    # Connect to WMS
    wms = WebMapService(WMS_URL, version="1.3.0")

    # Check if we need to tile (WMS has size limits)
    if width_px > MAX_TILE_SIZE or height_px > MAX_TILE_SIZE:
        # Tile the request
        print(f"  Tiling request (max {MAX_TILE_SIZE}px per tile)...")
        img_array = fetch_tiled(wms, layer, (minx, miny, maxx, maxy), width_px, height_px)
    else:
        # Single request
        img_array = fetch_wms_tile(wms, layer, (minx, miny, maxx, maxy), width_px, height_px)

    print(f"  Fetched {img_array.shape}")

    # Output path
    output_path = raw_output_path(
        city, neighbourhood,
        f"orthophoto_{output_suffix}_2021",
        extension="tif"
    )

    # Create transform
    transform = from_bounds(minx, miny, maxx, maxy, width_px, height_px)

    # Save as GeoTIFF
    print(f"  Saving to {output_path}...")

    # Handle different band counts (RGB has 3-4 bands, we want 3)
    if len(img_array.shape) == 2:
        # Grayscale
        count = 1
        data = img_array[np.newaxis, :, :]
    else:
        # RGB or RGBA - take first 3 bands
        count = 3
        data = img_array[:, :, :3].transpose(2, 0, 1)  # HWC -> CHW

    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        height=height_px,
        width=width_px,
        count=count,
        dtype=data.dtype,
        crs="EPSG:31370",
        transform=transform,
        compress="lzw",
    ) as dst:
        dst.write(data)

    # Log
    finished_at = datetime.now(timezone.utc)
    append_ingest_log(
        city=city,
        dataset=f"orthophoto_{output_suffix}",
        neighbourhood=neighbourhood,
        started_at=started_at,
        finished_at=finished_at,
        status="success",
        output_path=output_path,
        notes=f"Layer: {layer}, Resolution: {RESOLUTION_M}m",
    )

    print(f"  Done!")
    return output_path


def fetch_tiled(
    wms: WebMapService,
    layer: str,
    bbox: tuple[float, float, float, float],
    total_width: int,
    total_height: int,
) -> np.ndarray:
    """Fetch large area by tiling requests."""
    minx, miny, maxx, maxy = bbox

    # Calculate number of tiles needed
    n_tiles_x = (total_width + MAX_TILE_SIZE - 1) // MAX_TILE_SIZE
    n_tiles_y = (total_height + MAX_TILE_SIZE - 1) // MAX_TILE_SIZE

    tile_width_m = (maxx - minx) / n_tiles_x
    tile_height_m = (maxy - miny) / n_tiles_y

    # Initialize output array (assume RGBA, will trim later)
    result = None

    for ty in range(n_tiles_y):
        row_tiles = []
        for tx in range(n_tiles_x):
            # Calculate tile bounds
            t_minx = minx + tx * tile_width_m
            t_maxx = minx + (tx + 1) * tile_width_m
            t_miny = miny + ty * tile_height_m
            t_maxy = miny + (ty + 1) * tile_height_m

            # Calculate pixel size for this tile
            t_width = int(tile_width_m / RESOLUTION_M)
            t_height = int(tile_height_m / RESOLUTION_M)

            # Fetch tile
            tile = fetch_wms_tile(wms, layer, (t_minx, t_miny, t_maxx, t_maxy), t_width, t_height)
            row_tiles.append(tile)
            print(f"    Tile {ty * n_tiles_x + tx + 1}/{n_tiles_x * n_tiles_y}")

        # Stack row horizontally
        row = np.concatenate(row_tiles, axis=1)

        if result is None:
            result = row
        else:
            # Stack vertically (note: WMS returns top-to-bottom, so we prepend)
            result = np.concatenate([row, result], axis=0)

    return result


def ingest_orthophoto_summer(city: str, neighbourhood: str) -> tuple[Path, Path]:
    """Ingest both RGB and CIR summer orthophoto for a neighbourhood.

    Returns (rgb_path, cir_path).
    """
    print("=" * 60)
    print(f"Summer Orthophoto Ingest: {city}/{neighbourhood}")
    print("=" * 60)

    # Fetch RGB
    rgb_path = fetch_orthophoto(city, neighbourhood, RGB_LAYER, "rgb")

    # Fetch CIR (for NDVI)
    cir_path = fetch_orthophoto(city, neighbourhood, CIR_LAYER, "cir")

    print("\nComplete!")
    print(f"  RGB: {rgb_path}")
    print(f"  CIR: {cir_path}")

    return rgb_path, cir_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest summer orthophoto")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    ingest_orthophoto_summer(args.city, args.neighbourhood)
