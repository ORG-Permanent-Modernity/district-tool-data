"""Vegetation detection from NDVI (2021 CIR orthophoto).

Detects all green vegetation using NDVI thresholding on summer CIR imagery.
Uses 2021 orthophoto to capture recent plantings that would be missing from
the outdated DHM-II LiDAR (2013-2015).

The approach:
1. Compute NDVI from CIR bands (NIR, Red)
2. Threshold: NDVI >= 0.05 (any green vegetation)
3. Optional: height filter from nDSM (disabled by default due to temporal mismatch)
4. Morphological cleanup: opening + closing to remove noise
5. Vectorize to polygons with minimum area filter

Note: Height filtering is available but disabled by default because DHM-II
(2013-2015) misses trees planted since then. DHM-III expected 2028.

Usage:
    python -m src.clean.vegetation antwerp haringrode
    python -m src.clean.vegetation antwerp haringrode --ndvi 0.05 --height 0
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.warp import reproject, Resampling
from scipy import ndimage
from shapely.geometry import shape

from src.clean._common import CleaningLog, stable_uuid
from src.ingest._common import neighbourhood_path


# Default thresholds (finalized after testing)
DEFAULT_NDVI_THRESHOLD = 0.05  # Any green vegetation
DEFAULT_HEIGHT_THRESHOLD = 0.0  # Disabled - DHM-II too outdated
DEFAULT_MIN_AREA_M2 = 2.0


def load_and_resample(source_path: Path, target_shape: tuple, target_transform, target_crs) -> np.ndarray:
    """Load raster and resample to match target grid."""
    with rasterio.open(source_path) as src:
        source_data = src.read(1)
        source_transform = src.transform
        source_crs = src.crs
        source_nodata = src.nodata

        output = np.zeros(target_shape, dtype=np.float32)

        reproject(
            source=source_data,
            destination=output,
            src_transform=source_transform,
            src_crs=source_crs,
            dst_transform=target_transform,
            dst_crs=target_crs,
            resampling=Resampling.bilinear,
            src_nodata=source_nodata,
            dst_nodata=-9999,
        )

    return output


def create_canopy_mask(
    ndvi: np.ndarray,
    height: np.ndarray,
    ndvi_threshold: float,
    height_threshold: float,
    ndvi_nodata: float = -9999,
    height_nodata: float = -9999,
) -> np.ndarray:
    """Create binary canopy mask from NDVI and height layers."""
    # Valid data mask
    valid = (ndvi != ndvi_nodata) & (height != height_nodata)

    # Threshold masks
    is_green = ndvi >= ndvi_threshold
    is_tall = height >= height_threshold

    # Combine: must be green AND tall AND valid
    canopy = valid & is_green & is_tall

    return canopy.astype(np.uint8)


def morphological_cleanup(
    mask: np.ndarray,
    opening_size: int = 2,
    closing_size: int = 3,
) -> np.ndarray:
    """Clean up binary mask with morphological operations."""
    # Opening: removes small noise (isolated pixels)
    if opening_size > 0:
        struct_open = ndimage.generate_binary_structure(2, 1)
        struct_open = ndimage.iterate_structure(struct_open, opening_size)
        mask = ndimage.binary_opening(mask, structure=struct_open)

    # Closing: fills small gaps
    if closing_size > 0:
        struct_close = ndimage.generate_binary_structure(2, 1)
        struct_close = ndimage.iterate_structure(struct_close, closing_size)
        mask = ndimage.binary_closing(mask, structure=struct_close)

    return mask.astype(np.uint8)


def vectorize_mask(
    mask: np.ndarray,
    transform,
    crs,
    min_area_m2: float = 4.0,
) -> gpd.GeoDataFrame:
    """Convert binary mask to polygons."""
    polygons = []

    for geom, value in shapes(mask, transform=transform):
        if value == 1:  # Canopy pixels
            poly = shape(geom)
            if poly.area >= min_area_m2:
                polygons.append(poly)

    if not polygons:
        return gpd.GeoDataFrame(columns=["geometry"], crs=crs)

    return gpd.GeoDataFrame(geometry=polygons, crs=crs)


def compute_zonal_stats(gdf: gpd.GeoDataFrame, height_array: np.ndarray, transform) -> gpd.GeoDataFrame:
    """Compute height statistics for each polygon."""
    from rasterio.features import geometry_mask

    mean_heights = []
    max_heights = []

    for geom in gdf.geometry:
        # Create mask for this polygon
        mask = geometry_mask(
            [geom],
            out_shape=height_array.shape,
            transform=transform,
            invert=True,
        )

        # Extract heights within polygon
        heights = height_array[mask]
        valid = heights[heights > 0]

        if len(valid) > 0:
            mean_heights.append(float(np.mean(valid)))
            max_heights.append(float(np.max(valid)))
        else:
            mean_heights.append(0.0)
            max_heights.append(0.0)

    gdf = gdf.copy()
    gdf["mean_height_m"] = mean_heights
    gdf["max_height_m"] = max_heights

    return gdf


def clean_canopy_ndvi_height(
    city: str,
    neighbourhood: str,
    ndvi_threshold: float = DEFAULT_NDVI_THRESHOLD,
    height_threshold: float = DEFAULT_HEIGHT_THRESHOLD,
    min_area_m2: float = DEFAULT_MIN_AREA_M2,
    opening_size: int = 2,
    closing_size: int = 3,
    output_suffix: str = "",
    output_dir: Path | None = None,
) -> tuple[gpd.GeoDataFrame, dict]:
    """Create canopy polygons from NDVI + height thresholds.

    Returns (gdf, stats_dict).
    """
    started_at = datetime.now(timezone.utc)

    base_path = neighbourhood_path(city, neighbourhood)

    # Load nDSM as reference grid (1m resolution)
    ndsm_path = base_path / "reviewed" / "terrain_ndsm.tif"
    with rasterio.open(ndsm_path) as src:
        height = src.read(1)
        height_transform = src.transform
        height_crs = src.crs
        height_nodata = src.nodata if src.nodata else -9999
        height_shape = height.shape

    # Load and resample NDVI to match nDSM grid
    ndvi_path = base_path / "cleaned" / "ndvi.tif"
    ndvi = load_and_resample(ndvi_path, height_shape, height_transform, height_crs)

    print(f"  NDVI range: [{ndvi[ndvi != -9999].min():.3f}, {ndvi[ndvi != -9999].max():.3f}]")
    print(f"  Height range: [{height[height > 0].min():.1f}, {height[height > 0].max():.1f}]m")

    # Create canopy mask
    mask = create_canopy_mask(
        ndvi, height,
        ndvi_threshold, height_threshold,
        ndvi_nodata=-9999,
        height_nodata=height_nodata if height_nodata else 0,
    )
    pixels_before_cleanup = mask.sum()

    # Morphological cleanup
    mask = morphological_cleanup(mask, opening_size, closing_size)
    pixels_after_cleanup = mask.sum()

    print(f"  Canopy pixels: {pixels_before_cleanup:,} → {pixels_after_cleanup:,} after cleanup")

    # Vectorize
    gdf = vectorize_mask(mask, height_transform, height_crs, min_area_m2)

    if len(gdf) == 0:
        print("  No canopy polygons found")
        stats = {
            "polygons": 0,
            "total_area_ha": 0,
            "pixels_before": pixels_before_cleanup,
            "pixels_after": pixels_after_cleanup,
        }
        return gdf, stats

    # Compute zonal stats
    gdf = compute_zonal_stats(gdf, height, height_transform)

    # Add area and IDs
    gdf["area_m2"] = gdf.geometry.area
    gdf["id"] = [stable_uuid() for _ in range(len(gdf))]
    gdf = gdf[["id", "area_m2", "mean_height_m", "max_height_m", "geometry"]]

    total_area_ha = gdf.geometry.area.sum() / 10000

    # Save
    if output_dir is None:
        output_dir = base_path / "cleaned"

    if output_suffix:
        output_path = output_dir / f"canopy_ndvi_height_{output_suffix}.gpkg"
    else:
        output_path = output_dir / "canopy_ndvi_height.gpkg"

    gdf.to_file(output_path, driver="GPKG")

    print(f"  → {len(gdf)} polygons, {total_area_ha:.2f} ha")
    print(f"  Saved to {output_path.name}")

    stats = {
        "polygons": len(gdf),
        "total_area_ha": total_area_ha,
        "mean_height": gdf["mean_height_m"].mean() if len(gdf) > 0 else 0,
        "pixels_before": pixels_before_cleanup,
        "pixels_after": pixels_after_cleanup,
    }

    return gdf, stats


def run_batch_tests(city: str, neighbourhood: str):
    """Run multiple configurations and save results."""
    base_path = neighbourhood_path(city, neighbourhood)
    output_dir = base_path / "cleaned" / "canopy_ndvi_height_tests"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(f"NDVI + Height Canopy Detection: {city}/{neighbourhood}")
    print("=" * 60)

    # Test configurations: (name, ndvi, height, opening, closing)
    configs = [
        # Vary NDVI threshold
        ("ndvi_0.05_h2.0", 0.05, 2.0, 2, 3),
        ("ndvi_0.10_h2.0", 0.10, 2.0, 2, 3),
        ("ndvi_0.15_h2.0", 0.15, 2.0, 2, 3),
        ("ndvi_0.20_h2.0", 0.20, 2.0, 2, 3),

        # Vary height threshold
        ("ndvi_0.10_h1.5", 0.10, 1.5, 2, 3),
        ("ndvi_0.10_h2.5", 0.10, 2.5, 2, 3),
        ("ndvi_0.10_h3.0", 0.10, 3.0, 2, 3),

        # Combined variations
        ("ndvi_0.05_h1.5", 0.05, 1.5, 2, 3),  # Most inclusive
        ("ndvi_0.15_h2.5", 0.15, 2.5, 2, 3),  # Moderate
        ("ndvi_0.20_h3.0", 0.20, 3.0, 2, 3),  # Most restrictive

        # Less morphological cleanup
        ("ndvi_0.10_h2.0_minimal_cleanup", 0.10, 2.0, 1, 1),

        # More aggressive cleanup
        ("ndvi_0.10_h2.0_aggressive_cleanup", 0.10, 2.0, 3, 5),
    ]

    results = []

    for name, ndvi_thresh, height_thresh, opening, closing in configs:
        print(f"\nConfig: {name}")
        print(f"  ndvi>={ndvi_thresh}, height>={height_thresh}m, open={opening}, close={closing}")

        gdf, stats = clean_canopy_ndvi_height(
            city, neighbourhood,
            ndvi_threshold=ndvi_thresh,
            height_threshold=height_thresh,
            opening_size=opening,
            closing_size=closing,
            output_suffix=name,
            output_dir=output_dir,
        )

        results.append({
            "config": name,
            "ndvi": ndvi_thresh,
            "height": height_thresh,
            **stats,
        })

    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"{'Config':<40} {'Polygons':>10} {'Area (ha)':>10}")
    print("-" * 60)
    for r in results:
        print(f"{r['config']:<40} {r['polygons']:>10} {r['total_area_ha']:>10.2f}")

    print(f"\nResults saved to: {output_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NDVI + height canopy detection")
    parser.add_argument("city", help="City name")
    parser.add_argument("neighbourhood", help="Neighbourhood name")
    parser.add_argument("--ndvi", type=float, default=None, help="NDVI threshold")
    parser.add_argument("--height", type=float, default=None, help="Height threshold (m)")
    parser.add_argument("--batch", action="store_true", help="Run batch tests")
    args = parser.parse_args()

    if args.batch:
        run_batch_tests(args.city, args.neighbourhood)
    elif args.ndvi is not None and args.height is not None:
        clean_canopy_ndvi_height(
            args.city, args.neighbourhood,
            ndvi_threshold=args.ndvi,
            height_threshold=args.height,
        )
    else:
        # Default single run
        clean_canopy_ndvi_height(args.city, args.neighbourhood)
