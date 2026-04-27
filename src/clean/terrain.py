"""Clean terrain rasters (DTM, DSM) and compute nDSM.

This script handles all terrain data for a neighbourhood:
- Verifies raw DTM and DSM rasters
- Copies/converts to cleaned/ with cleaning logs
- Computes nDSM = DSM - DTM (clipped to >= 0)
- Optionally promotes to reviewed/

Decisions:
- No mosaicking needed if download portal provided single clipped file
- nDSM negative values clipped to 0 (water bodies, tile seams)
- Output format: GeoTIFF (Cloud-Optimized if rasterio supports it)
- CRS must be EPSG:31370

Usage:
    python -m src.clean.terrain antwerp haringrode [--promote]
"""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS

from src.clean._common import RasterCleaningLog
from src.ingest._common import (
    append_ingest_log,
    get_data_root,
    load_aoi,
    neighbourhood_path,
)


def verify_raster(path: Path, expected_crs: int = 31370) -> dict:
    """Verify a raster and return its properties."""
    with rasterio.open(path) as src:
        if src.crs.to_epsg() != expected_crs:
            raise ValueError(f"Expected EPSG:{expected_crs}, got {src.crs}")
        return {
            "crs": str(src.crs),
            "resolution": src.res[0],
            "shape": src.shape,
            "bounds": tuple(src.bounds),
            "dtype": src.dtypes[0],
            "nodata": src.nodata,
        }


def copy_raster(src_path: Path, dst_path: Path) -> None:
    """Copy a raster file to destination."""
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_path, dst_path)


def compute_ndsm(
    dsm_path: Path,
    dtm_path: Path,
    output_path: Path,
    nodata: float = -9999.0,
) -> dict:
    """Compute nDSM = DSM - DTM, clipping negatives to 0.

    Returns properties dict for the output raster.
    """
    with rasterio.open(dsm_path) as dsm_src, rasterio.open(dtm_path) as dtm_src:
        # Verify same extent and resolution
        if dsm_src.shape != dtm_src.shape:
            raise ValueError(
                f"DSM shape {dsm_src.shape} != DTM shape {dtm_src.shape}"
            )
        if dsm_src.bounds != dtm_src.bounds:
            raise ValueError(
                f"DSM bounds {dsm_src.bounds} != DTM bounds {dtm_src.bounds}"
            )

        dsm = dsm_src.read(1)
        dtm = dtm_src.read(1)

        # Compute nDSM
        ndsm = dsm - dtm

        # Handle nodata
        dsm_nodata = dsm_src.nodata or nodata
        dtm_nodata = dtm_src.nodata or nodata
        nodata_mask = (dsm == dsm_nodata) | (dtm == dtm_nodata)

        # Clip negative values to 0 (water bodies, tile seams)
        n_negative = np.sum((ndsm < 0) & ~nodata_mask)
        ndsm = np.clip(ndsm, 0, None)

        # Set nodata
        ndsm[nodata_mask] = nodata

        # Write output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        profile = dsm_src.profile.copy()
        profile.update(dtype="float32", nodata=nodata)

        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(ndsm.astype("float32"), 1)

        return {
            "crs": str(dsm_src.crs),
            "resolution": dsm_src.res[0],
            "shape": dsm_src.shape,
            "bounds": tuple(dsm_src.bounds),
            "dtype": "float32",
            "nodata": nodata,
            "n_negative_clipped": int(n_negative),
        }


def process_terrain(
    city: str,
    neighbourhood: str,
    promote: bool = False,
) -> None:
    """Process all terrain data for a neighbourhood."""
    now = datetime.now(timezone.utc)
    base = neighbourhood_path(city, neighbourhood)
    raw_dir = base / "raw"
    cleaned_dir = base / "cleaned"
    reviewed_dir = base / "reviewed"

    # Find raw files (check both dated folders and direct files)
    dtm_candidates = list(raw_dir.glob("dhm_dtm_*/*.tif")) + list(
        raw_dir.glob("dhm_dtm_*.tif")
    )
    dsm_candidates = list(raw_dir.glob("dhm_dsm_*/*.tif")) + list(
        raw_dir.glob("dhm_dsm_*.tif")
    )

    if not dtm_candidates:
        raise FileNotFoundError(f"No DTM files found in {raw_dir}/dhm_dtm_*/")
    if not dsm_candidates:
        raise FileNotFoundError(f"No DSM files found in {raw_dir}/dhm_dsm_*/")

    dtm_raw = dtm_candidates[0]
    dsm_raw = dsm_candidates[0]

    print(f"Processing DTM: {dtm_raw}")
    print(f"Processing DSM: {dsm_raw}")

    # Verify and process DTM
    dtm_props = verify_raster(dtm_raw)
    dtm_cleaned = cleaned_dir / "terrain_dtm.tif"
    copy_raster(dtm_raw, dtm_cleaned)

    dtm_log = RasterCleaningLog(
        dataset="terrain_dtm",
        raw_input_path=str(dtm_raw),
        cleaned_output_path=str(dtm_cleaned),
        started_at=now,
        finished_at=datetime.now(timezone.utc),
        crs=dtm_props["crs"],
        resolution_m=dtm_props["resolution"],
        shape=dtm_props["shape"],
        bounds=dtm_props["bounds"],
        dtype=dtm_props["dtype"],
        nodata=dtm_props["nodata"],
        tiles_mosaicked=1,
        decisions=[
            "Single pre-clipped file from download portal - no mosaicking needed",
            "CRS verified as EPSG:31370",
        ],
        anomalies=[],
    )
    dtm_log.save()
    print(f"  -> {dtm_cleaned}")

    # Verify and process DSM
    dsm_props = verify_raster(dsm_raw)
    dsm_cleaned = cleaned_dir / "terrain_dsm.tif"
    copy_raster(dsm_raw, dsm_cleaned)

    dsm_log = RasterCleaningLog(
        dataset="terrain_dsm",
        raw_input_path=str(dsm_raw),
        cleaned_output_path=str(dsm_cleaned),
        started_at=now,
        finished_at=datetime.now(timezone.utc),
        crs=dsm_props["crs"],
        resolution_m=dsm_props["resolution"],
        shape=dsm_props["shape"],
        bounds=dsm_props["bounds"],
        dtype=dsm_props["dtype"],
        nodata=dsm_props["nodata"],
        tiles_mosaicked=1,
        decisions=[
            "Single pre-clipped file from download portal - no mosaicking needed",
            "CRS verified as EPSG:31370",
        ],
        anomalies=[],
    )
    dsm_log.save()
    print(f"  -> {dsm_cleaned}")

    # Compute nDSM
    print("Computing nDSM...")
    ndsm_cleaned = cleaned_dir / "terrain_ndsm.tif"
    ndsm_props = compute_ndsm(dsm_cleaned, dtm_cleaned, ndsm_cleaned)

    ndsm_log = RasterCleaningLog(
        dataset="terrain_ndsm",
        raw_input_path=f"{dsm_cleaned}, {dtm_cleaned}",
        cleaned_output_path=str(ndsm_cleaned),
        started_at=now,
        finished_at=datetime.now(timezone.utc),
        crs=ndsm_props["crs"],
        resolution_m=ndsm_props["resolution"],
        shape=ndsm_props["shape"],
        bounds=ndsm_props["bounds"],
        dtype=ndsm_props["dtype"],
        nodata=ndsm_props["nodata"],
        tiles_mosaicked=0,
        decisions=[
            "Computed as DSM - DTM",
            "Negative values clipped to 0 (water bodies, tile seams)",
        ],
        anomalies=[
            f"{ndsm_props['n_negative_clipped']} pixels with negative values clipped to 0"
        ]
        if ndsm_props["n_negative_clipped"] > 0
        else [],
    )
    ndsm_log.save()
    print(f"  -> {ndsm_cleaned}")
    print(f"     ({ndsm_props['n_negative_clipped']} negative pixels clipped to 0)")

    # Promote to reviewed if requested
    if promote:
        print("\nPromoting to reviewed/...")
        reviewed_dir.mkdir(parents=True, exist_ok=True)

        for src, name in [
            (dtm_cleaned, "terrain_dtm.tif"),
            (dsm_cleaned, "terrain_dsm.tif"),
            (ndsm_cleaned, "terrain_ndsm.tif"),
        ]:
            dst = reviewed_dir / name
            copy_raster(src, dst)
            print(f"  -> {dst}")

    # Log ingest for DTM and DSM
    for dataset, raw_path in [("dhm_dtm", dtm_raw), ("dhm_dsm", dsm_raw)]:
        append_ingest_log(
            city=city,
            dataset=dataset,
            neighbourhood=neighbourhood,
            started_at=now,
            finished_at=datetime.now(timezone.utc),
            status="success",
            output_path=raw_path,
            tiles_fetched=1,
            notes="Manual download from download.vlaanderen.be portal",
        )

    print("\nDone!")
    print("\nNext steps:")
    if not promote:
        print("  1. Review cleaned files in QGIS")
        print("  2. If OK, run with --promote to copy to reviewed/")
        print("  3. Update meta.yaml with review info")
    else:
        print("  1. Update meta.yaml with review info")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean terrain data")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    parser.add_argument(
        "--promote",
        action="store_true",
        help="Also copy to reviewed/",
    )
    args = parser.parse_args()

    process_terrain(args.city, args.neighbourhood, args.promote)
