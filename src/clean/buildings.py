"""Clean GRB buildings for a neighbourhood.

This script processes GRB building footprints:
- Clips strictly to AOI (removes buffer zone)
- Drops buildings < minimum area threshold
- Fixes invalid geometries
- Computes area_m2 for each building
- Computes height_m from nDSM zonal statistics (median)
- Adds height_confidence flag for temporal mismatch detection
- Adds stable UUIDs
- Initializes use_hint = 'unknown'
- Computes estimated_storeys from height

Decisions:
- Minimum area threshold: 10 m² (drops sheds, bus shelters, etc.)
- Height from nDSM: median value within footprint
- Storeys estimate: height_m / 3.0, rounded
- Buildings with null height (no nDSM coverage) are kept
- Height confidence: 'high' if >= 2.5m, 'low' if < 2.5m (suspect temporal mismatch)

Height confidence rationale:
  DHM-II was captured 2013-2015. Buildings with near-zero nDSM heights are likely:
  1. Built AFTER the LiDAR survey (not in DSM, appear as ground level)
  2. Demolished SINCE GRB was updated (in GRB but gone from reality)
  3. Very flat structures (garages, single-storey — legitimate but rare < 2.5m)
  A 2.5m threshold catches most suspect cases while allowing legitimate low buildings.

Usage:
    python -m src.clean.buildings antwerp haringrode
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.mask import mask as rasterio_mask
from shapely.geometry import mapping

from src.clean._common import CleaningLog, fix_invalid_geometries, stable_uuid
from src.ingest._common import get_data_root, load_aoi, neighbourhood_path


MIN_AREA_M2 = 10.0  # Minimum building footprint area
MIN_CONFIDENT_HEIGHT_M = 2.5  # Heights below this are flagged as low confidence


def compute_zonal_median(
    gdf: gpd.GeoDataFrame,
    raster_path: Path,
    nodata: float = -9999.0,
) -> list[float | None]:
    """Compute median raster value within each polygon.

    Returns a list of median values (or None if no valid pixels).
    """
    heights = []
    with rasterio.open(raster_path) as src:
        for geom in gdf.geometry:
            try:
                # Extract pixels within the polygon
                out_image, _ = rasterio_mask(
                    src, [mapping(geom)], crop=True, nodata=nodata
                )
                pixels = out_image[0]  # First band
                valid_pixels = pixels[pixels != nodata]
                if len(valid_pixels) > 0:
                    heights.append(float(np.median(valid_pixels)))
                else:
                    heights.append(None)
            except Exception:
                heights.append(None)
    return heights


def clean_buildings(
    city: str,
    neighbourhood: str,
    min_area_m2: float = MIN_AREA_M2,
) -> CleaningLog:
    """Clean buildings for a neighbourhood.

    Returns the CleaningLog with details of what was done.
    """
    now = datetime.now(timezone.utc)
    base = neighbourhood_path(city, neighbourhood)

    # Find raw input
    raw_candidates = sorted(base.glob("raw/grb_gebouwen_*.gpkg"), reverse=True)
    if not raw_candidates:
        raise FileNotFoundError(f"No raw GRB buildings found in {base}/raw/")
    raw_path = raw_candidates[0]

    # Output paths
    cleaned_path = base / "cleaned" / "buildings.gpkg"
    ndsm_path = base / "reviewed" / "terrain_ndsm.tif"

    # Load AOI
    aoi = load_aoi(city, neighbourhood)

    # Start cleaning log
    log = CleaningLog(
        dataset="buildings",
        raw_input_path=str(raw_path),
        cleaned_output_path=str(cleaned_path),
        started_at=now,
    )

    # Load raw data
    print(f"Loading raw buildings from {raw_path}...")
    gdf = gpd.read_file(raw_path)
    log.rows_in = len(gdf)
    print(f"  Loaded {len(gdf)} features")

    # Fix invalid geometries
    print("Fixing invalid geometries...")
    n_invalid = (~gdf.geometry.is_valid).sum()
    gdf, n_dropped_invalid = fix_invalid_geometries(gdf)
    if n_invalid > 0:
        log.anomalies.append(f"{n_invalid} invalid geometries found, {n_dropped_invalid} unfixable and dropped")
        print(f"  Fixed {n_invalid - n_dropped_invalid}, dropped {n_dropped_invalid}")

    # Clip to AOI (strict, no buffer)
    print("Clipping to AOI...")
    n_before_clip = len(gdf)
    aoi_geom = aoi.union_all()
    gdf = gdf.clip(aoi_geom)
    n_clipped = n_before_clip - len(gdf)
    log.rows_dropped["outside_aoi"] = n_clipped
    log.decisions.append("Clipped strictly to AOI boundary (no buffer)")
    print(f"  Removed {n_clipped} features outside AOI")

    # Compute area
    print("Computing footprint areas...")
    gdf["area_m2"] = gdf.geometry.area
    log.columns_added.append("area_m2")

    # Drop small buildings
    print(f"Dropping buildings < {min_area_m2} m²...")
    small_mask = gdf["area_m2"] < min_area_m2
    n_small = small_mask.sum()
    gdf = gdf[~small_mask].copy()
    log.rows_dropped[f"area_below_{min_area_m2}m2"] = n_small
    log.decisions.append(f"Dropped buildings with area < {min_area_m2} m²")
    print(f"  Removed {n_small} small features")

    # Compute heights from nDSM
    if ndsm_path.exists():
        print(f"Computing heights from nDSM...")
        heights = compute_zonal_median(gdf, ndsm_path)
        gdf["height_m"] = heights
        gdf["height_source"] = ["dhm_derived" if h is not None else None for h in heights]
        n_null_height = gdf["height_m"].isna().sum()
        log.columns_added.extend(["height_m", "height_source"])
        log.decisions.append("Height computed as median nDSM value within footprint")
        if n_null_height > 0:
            log.anomalies.append(f"{n_null_height} buildings with null height (no nDSM coverage)")
        print(f"  {len(gdf) - n_null_height} buildings with heights, {n_null_height} null")

        # Compute height confidence
        # Low confidence = height < threshold (likely temporal mismatch with DHM-II)
        print(f"Computing height confidence (threshold: {MIN_CONFIDENT_HEIGHT_M}m)...")

        def get_confidence(h):
            if h is None:
                return None
            elif h < MIN_CONFIDENT_HEIGHT_M:
                return "low"
            else:
                return "high"

        gdf["height_confidence"] = gdf["height_m"].apply(get_confidence)
        log.columns_added.append("height_confidence")

        n_low_confidence = (gdf["height_confidence"] == "low").sum()
        n_high_confidence = (gdf["height_confidence"] == "high").sum()
        log.decisions.append(
            f"height_confidence: 'high' if >= {MIN_CONFIDENT_HEIGHT_M}m, "
            f"'low' if < {MIN_CONFIDENT_HEIGHT_M}m (suspect temporal mismatch with DHM-II 2013-2015)"
        )
        if n_low_confidence > 0:
            log.anomalies.append(
                f"{n_low_confidence} buildings with low height confidence "
                f"(height < {MIN_CONFIDENT_HEIGHT_M}m, possible post-2015 construction or demolition)"
            )
        print(f"  {n_high_confidence} high confidence, {n_low_confidence} low confidence")
    else:
        print(f"  WARNING: nDSM not found at {ndsm_path}, skipping height computation")
        gdf["height_m"] = None
        gdf["height_source"] = None
        gdf["height_confidence"] = None
        log.anomalies.append("nDSM not available - heights not computed")

    # Compute estimated storeys
    print("Computing estimated storeys...")
    gdf["estimated_storeys"] = gdf["height_m"].apply(
        lambda h: int(round(h / 3.0)) if h is not None and h > 0 else None
    )
    log.columns_added.append("estimated_storeys")
    log.decisions.append("Estimated storeys = round(height_m / 3.0)")

    # Add stable UUIDs
    print("Adding stable UUIDs...")
    gdf["id"] = [stable_uuid() for _ in range(len(gdf))]
    gdf["source_id"] = gdf["OIDN"].astype(str)
    log.columns_added.extend(["id", "source_id"])
    log.columns_renamed["OIDN"] = "source_id (kept as separate column)"

    # Initialize use_hint
    gdf["use_hint"] = "unknown"
    log.columns_added.append("use_hint")
    log.decisions.append("use_hint initialized to 'unknown' (population deferred)")

    # Initialize roof_type as null
    gdf["roof_type"] = None
    log.columns_added.append("roof_type")
    log.decisions.append("roof_type set to null (GRB 3D not processed)")

    # Build attrs column with remaining source attributes
    print("Building attrs column...")
    attr_cols = ["UIDN", "VERSIE", "BEGINDATUM", "VERSDATUM", "TYPE", "LBLTYPE", "OPNDATUM", "BGNINV", "LBLBGNINV"]
    existing_cols = [c for c in attr_cols if c in gdf.columns]
    gdf["attrs"] = gdf[existing_cols].apply(lambda row: row.to_dict(), axis=1)
    log.columns_added.append("attrs")

    # Select final columns in schema order
    final_cols = [
        "id",
        "source_id",
        "geometry",
        "height_m",
        "height_source",
        "height_confidence",
        "roof_type",
        "area_m2",
        "estimated_storeys",
        "use_hint",
        "attrs",
    ]
    gdf = gdf[final_cols]

    # Save
    print(f"Saving to {cleaned_path}...")
    cleaned_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(cleaned_path, driver="GPKG")

    # Finalize log
    log.rows_out = len(gdf)
    log.finished_at = datetime.now(timezone.utc)
    log.save()

    print(f"\nDone! {log.rows_in} -> {log.rows_out} buildings")
    print(f"Cleaning log saved to {cleaned_path}.cleaning_log.yaml")

    return log


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean GRB buildings")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    parser.add_argument(
        "--min-area",
        type=float,
        default=MIN_AREA_M2,
        help=f"Minimum building area in m² (default: {MIN_AREA_M2})",
    )
    args = parser.parse_args()

    clean_buildings(args.city, args.neighbourhood, args.min_area)
