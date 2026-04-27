"""Derive canopy coverage from nDSM and building footprints.

This script creates a complete tree canopy dataset by:
1. Loading the nDSM (heights above ground)
2. Masking out building footprints
3. Thresholding to identify vegetation > min height
4. Applying morphological cleanup
5. Vectorizing to polygons with height statistics

This supplements the municipal tree inventory (which only covers city-maintained
trees) with complete canopy coverage including private gardens.

Outputs:
- canopy_chm.tif: Canopy Height Model (nDSM with buildings masked)
- canopy_polygons.gpkg: Vectorized canopy polygons

Known limitations:
- DHM-II is 2013-2015: temporal mismatch with current vegetation
- Tall hedges (>2.5m) are included as canopy
- Green roofs are excluded (masked with buildings)

Usage:
    python -m src.clean.canopy antwerp haringrode
    python -m src.clean.canopy antwerp haringrode --min-height 3.0 --promote
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio import features
from rasterio.transform import Affine
from scipy import ndimage
from shapely.geometry import shape

from src.clean._common import CleaningLog, RasterCleaningLog, stable_uuid
from src.ingest._common import neighbourhood_path


# Default parameters
MIN_HEIGHT_M = 2.5  # Minimum canopy height (above hedges)
BUILDING_BUFFER_M = 1.0  # Buffer around buildings to avoid edge effects
MIN_CANOPY_AREA_M2 = 4.0  # Minimum polygon area (2x2 pixels)
NODATA = -9999.0


def create_building_mask(
    buildings: gpd.GeoDataFrame,
    shape: tuple[int, int],
    transform: Affine,
    buffer_m: float = BUILDING_BUFFER_M,
) -> np.ndarray:
    """Rasterize building footprints to a boolean mask.

    Args:
        buildings: Building footprints GeoDataFrame
        shape: Output raster shape (height, width)
        transform: Rasterio Affine transform
        buffer_m: Buffer distance around buildings in metres

    Returns:
        Boolean array: True where buildings exist, False elsewhere
    """
    if len(buildings) == 0:
        return np.zeros(shape, dtype=bool)

    # Buffer the geometries
    buffered = buildings.copy()
    buffered["geometry"] = buffered.geometry.buffer(buffer_m)

    # Rasterize
    mask = features.rasterize(
        [(geom, 1) for geom in buffered.geometry],
        out_shape=shape,
        transform=transform,
        fill=0,
        dtype=np.uint8,
    )

    return mask.astype(bool)


def compute_canopy_height_model(
    ndsm_path: Path,
    buildings_path: Path,
    output_path: Path,
    building_buffer_m: float = BUILDING_BUFFER_M,
    nodata: float = NODATA,
) -> dict:
    """Create Canopy Height Model by masking buildings from nDSM.

    Args:
        ndsm_path: Path to nDSM raster
        buildings_path: Path to buildings GeoPackage
        output_path: Path for output CHM raster
        building_buffer_m: Buffer around buildings
        nodata: Nodata value for output

    Returns:
        Dict with stats for the cleaning log
    """
    # Load nDSM
    with rasterio.open(ndsm_path) as src:
        ndsm = src.read(1)
        profile = src.profile.copy()
        transform = src.transform
        src_nodata = src.nodata or nodata

        # Create nodata mask from source
        nodata_mask = ndsm == src_nodata

    # Load buildings
    buildings = gpd.read_file(buildings_path)

    # Create building mask
    building_mask = create_building_mask(
        buildings,
        shape=ndsm.shape,
        transform=transform,
        buffer_m=building_buffer_m,
    )

    # Create CHM: copy nDSM, set buildings to nodata
    chm = ndsm.copy()
    chm[building_mask] = nodata
    chm[nodata_mask] = nodata

    # Count stats
    n_building_pixels = building_mask.sum()
    n_valid_pixels = (~nodata_mask & ~building_mask).sum()

    # Update profile
    profile.update(dtype="float32", nodata=nodata)

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(chm.astype("float32"), 1)

    return {
        "shape": ndsm.shape,
        "transform": transform,
        "crs": profile["crs"],
        "resolution": abs(transform.a),
        "n_building_pixels": int(n_building_pixels),
        "n_valid_pixels": int(n_valid_pixels),
        "nodata": nodata,
    }


def threshold_canopy(
    chm_array: np.ndarray,
    nodata: float,
    min_height_m: float = MIN_HEIGHT_M,
    apply_opening: bool = True,
    apply_closing: bool = True,
    opening_size: int = 2,
    closing_size: int = 3,
) -> np.ndarray:
    """Apply height threshold and morphological cleanup.

    Args:
        chm_array: Canopy Height Model array
        nodata: Nodata value in the array
        min_height_m: Minimum height to count as canopy
        apply_opening: Apply morphological opening to remove noise
        apply_closing: Apply morphological closing to fill gaps
        opening_size: Kernel size for opening operation
        closing_size: Kernel size for closing operation

    Returns:
        Binary mask: True = canopy, False = not canopy
    """
    # Create valid data mask
    valid_mask = chm_array != nodata

    # Threshold: height > min_height
    canopy_mask = (chm_array > min_height_m) & valid_mask

    # Morphological opening: removes small isolated pixels (noise)
    if apply_opening and opening_size > 0:
        struct = ndimage.generate_binary_structure(2, 1)
        struct = ndimage.iterate_structure(struct, opening_size)
        canopy_mask = ndimage.binary_opening(canopy_mask, structure=struct)

    # Morphological closing: fills small holes within canopy
    if apply_closing and closing_size > 0:
        struct = ndimage.generate_binary_structure(2, 1)
        struct = ndimage.iterate_structure(struct, closing_size)
        canopy_mask = ndimage.binary_closing(canopy_mask, structure=struct)

    return canopy_mask


def vectorize_canopy(
    binary_mask: np.ndarray,
    chm_array: np.ndarray,
    transform: Affine,
    nodata: float,
    crs_epsg: int = 31370,
    min_area_m2: float = MIN_CANOPY_AREA_M2,
) -> gpd.GeoDataFrame:
    """Convert binary canopy mask to vector polygons with height stats.

    Args:
        binary_mask: Binary canopy mask
        chm_array: CHM array for computing height statistics
        transform: Rasterio Affine transform
        nodata: Nodata value in CHM
        crs_epsg: Output CRS EPSG code
        min_area_m2: Minimum polygon area to keep

    Returns:
        GeoDataFrame with canopy polygons and height statistics
    """
    # Extract polygon shapes from binary mask
    shapes_gen = features.shapes(
        binary_mask.astype(np.uint8),
        mask=binary_mask,
        transform=transform,
    )

    records = []
    for geom_dict, value in shapes_gen:
        if value == 0:
            continue

        geom = shape(geom_dict)
        area = geom.area

        # Filter by minimum area
        if area < min_area_m2:
            continue

        # Compute zonal statistics for this polygon
        # Rasterize the single polygon to get a mask
        poly_mask = features.rasterize(
            [(geom, 1)],
            out_shape=chm_array.shape,
            transform=transform,
            fill=0,
            dtype=np.uint8,
        ).astype(bool)

        # Get heights within polygon (excluding nodata)
        heights = chm_array[poly_mask & (chm_array != nodata)]

        if len(heights) > 0:
            mean_height = float(np.mean(heights))
            max_height = float(np.max(heights))
        else:
            mean_height = None
            max_height = None

        records.append({
            "id": stable_uuid(),
            "geometry": geom,
            "area_m2": area,
            "mean_height_m": mean_height,
            "max_height_m": max_height,
        })

    # Create GeoDataFrame
    if len(records) == 0:
        # Return empty GeoDataFrame with correct schema
        return gpd.GeoDataFrame(
            columns=["id", "geometry", "area_m2", "mean_height_m", "max_height_m"],
            crs=f"EPSG:{crs_epsg}",
        )

    gdf = gpd.GeoDataFrame(records, crs=f"EPSG:{crs_epsg}")
    return gdf


def clean_canopy(
    city: str,
    neighbourhood: str,
    min_height_m: float = MIN_HEIGHT_M,
    building_buffer_m: float = BUILDING_BUFFER_M,
    min_canopy_area_m2: float = MIN_CANOPY_AREA_M2,
    apply_morphological: bool = True,
    promote: bool = False,
) -> tuple[RasterCleaningLog, CleaningLog]:
    """Derive canopy from nDSM and buildings.

    Produces:
    - cleaned/canopy_chm.tif: Canopy Height Model
    - cleaned/canopy_polygons.gpkg: Vectorized canopy polygons

    Returns:
        Tuple of (raster_log, vector_log) cleaning logs.
    """
    now = datetime.now(timezone.utc)
    base = neighbourhood_path(city, neighbourhood)

    # Input paths (from reviewed/)
    ndsm_path = base / "reviewed" / "terrain_ndsm.tif"
    buildings_path = base / "reviewed" / "buildings.gpkg"

    if not ndsm_path.exists():
        raise FileNotFoundError(f"nDSM not found at {ndsm_path}")
    if not buildings_path.exists():
        raise FileNotFoundError(f"Buildings not found at {buildings_path}")

    # Output paths
    chm_path = base / "cleaned" / "canopy_chm.tif"
    polygons_path = base / "cleaned" / "canopy_polygons.gpkg"

    print(f"=== Canopy Detection for {city}/{neighbourhood} ===")
    print(f"Parameters: min_height={min_height_m}m, building_buffer={building_buffer_m}m")

    # Step 1: Compute Canopy Height Model
    print("\n1. Computing Canopy Height Model...")
    chm_stats = compute_canopy_height_model(
        ndsm_path=ndsm_path,
        buildings_path=buildings_path,
        output_path=chm_path,
        building_buffer_m=building_buffer_m,
    )
    print(f"   Building pixels masked: {chm_stats['n_building_pixels']:,}")
    print(f"   Valid canopy pixels: {chm_stats['n_valid_pixels']:,}")

    # Step 2: Threshold and clean
    print("\n2. Thresholding canopy...")
    with rasterio.open(chm_path) as src:
        chm_array = src.read(1)
        transform = src.transform

    canopy_mask = threshold_canopy(
        chm_array=chm_array,
        nodata=NODATA,
        min_height_m=min_height_m,
        apply_opening=apply_morphological,
        apply_closing=apply_morphological,
    )

    n_canopy_pixels = canopy_mask.sum()
    canopy_area_ha = n_canopy_pixels * (chm_stats["resolution"] ** 2) / 10000
    print(f"   Canopy pixels: {n_canopy_pixels:,} ({canopy_area_ha:.2f} ha)")

    # Step 3: Vectorize
    print("\n3. Vectorizing to polygons...")
    canopy_gdf = vectorize_canopy(
        binary_mask=canopy_mask,
        chm_array=chm_array,
        transform=transform,
        nodata=NODATA,
        min_area_m2=min_canopy_area_m2,
    )

    n_polygons = len(canopy_gdf)
    total_area_ha = canopy_gdf["area_m2"].sum() / 10000 if n_polygons > 0 else 0
    mean_height = canopy_gdf["mean_height_m"].mean() if n_polygons > 0 else 0
    print(f"   Polygons: {n_polygons:,}")
    print(f"   Total area: {total_area_ha:.2f} ha")
    print(f"   Mean canopy height: {mean_height:.1f}m")

    # Save polygons
    print(f"\n4. Saving outputs...")
    polygons_path.parent.mkdir(parents=True, exist_ok=True)
    canopy_gdf.to_file(polygons_path, driver="GPKG")

    # Create raster cleaning log
    raster_log = RasterCleaningLog(
        dataset="canopy_chm",
        raw_input_path=f"{ndsm_path}, {buildings_path}",
        cleaned_output_path=str(chm_path),
        started_at=now,
        finished_at=datetime.now(timezone.utc),
        crs=str(chm_stats["crs"]),
        resolution_m=chm_stats["resolution"],
        shape=chm_stats["shape"],
        bounds=(0, 0, 0, 0),  # Would need to extract from raster
        dtype="float32",
        nodata=NODATA,
        tiles_mosaicked=0,
        decisions=[
            f"Derived from nDSM with buildings masked (buffer={building_buffer_m}m)",
            f"Building pixels set to nodata ({chm_stats['n_building_pixels']:,} pixels)",
        ],
        anomalies=[],
    )
    raster_log.save()

    # Create vector cleaning log
    vector_log = CleaningLog(
        dataset="canopy_polygons",
        raw_input_path=str(chm_path),
        cleaned_output_path=str(polygons_path),
        started_at=now,
    )
    vector_log.rows_in = n_canopy_pixels
    vector_log.rows_out = n_polygons
    vector_log.columns_added = ["id", "area_m2", "mean_height_m", "max_height_m"]
    vector_log.decisions = [
        f"Height threshold: > {min_height_m}m",
        f"Morphological cleanup: {'yes' if apply_morphological else 'no'}",
        f"Minimum polygon area: {min_canopy_area_m2} m²",
        "Includes all vegetation (private gardens, hedges > threshold)",
    ]
    if n_polygons == 0:
        vector_log.anomalies.append("No canopy polygons detected")
    vector_log.finished_at = datetime.now(timezone.utc)
    vector_log.save()

    print(f"\nDone!")
    print(f"  CHM: {chm_path}")
    print(f"  Polygons: {polygons_path}")

    # Promote if requested
    if promote:
        print("\nPromoting to reviewed/...")
        reviewed_dir = base / "reviewed"
        import shutil
        shutil.copy(chm_path, reviewed_dir / "canopy_chm.tif")
        shutil.copy(polygons_path, reviewed_dir / "canopy_polygons.gpkg")
        print("  Promoted!")

    return raster_log, vector_log


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Derive canopy from nDSM")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    parser.add_argument(
        "--min-height",
        type=float,
        default=MIN_HEIGHT_M,
        help=f"Minimum canopy height in metres (default: {MIN_HEIGHT_M})",
    )
    parser.add_argument(
        "--building-buffer",
        type=float,
        default=BUILDING_BUFFER_M,
        help=f"Buffer around buildings in metres (default: {BUILDING_BUFFER_M})",
    )
    parser.add_argument(
        "--min-area",
        type=float,
        default=MIN_CANOPY_AREA_M2,
        help=f"Minimum polygon area in m² (default: {MIN_CANOPY_AREA_M2})",
    )
    parser.add_argument(
        "--no-morphological",
        action="store_true",
        help="Skip morphological cleanup operations",
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help="Promote outputs to reviewed/ immediately",
    )
    args = parser.parse_args()

    clean_canopy(
        args.city,
        args.neighbourhood,
        min_height_m=args.min_height,
        building_buffer_m=args.building_buffer,
        min_canopy_area_m2=args.min_area,
        apply_morphological=not args.no_morphological,
        promote=args.promote,
    )
