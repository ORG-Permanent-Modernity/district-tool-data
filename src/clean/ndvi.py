"""Compute NDVI from Color-Infrared (CIR) orthophoto.

NDVI (Normalized Difference Vegetation Index) measures vegetation health/presence.
Values range from -1 to 1, where:
  - > 0.3: healthy vegetation
  - 0.1 to 0.3: sparse vegetation, stressed plants
  - < 0.1: bare soil, water, built surfaces

The CIR orthophoto from Digitaal Vlaanderen has bands: NIR, Red, Green (false color).

Usage:
    python -m src.clean.ndvi antwerp haringrode
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio

from src.clean._common import RasterCleaningLog
from src.ingest._common import neighbourhood_path


def compute_ndvi(cir_path: Path, output_path: Path) -> dict:
    """Compute NDVI from CIR orthophoto.

    CIR bands are: [NIR, Red, Green] (indices 0, 1, 2).
    NDVI = (NIR - Red) / (NIR + Red)

    Returns dict with statistics.
    """
    with rasterio.open(cir_path) as src:
        # Read NIR (band 1) and Red (band 2)
        nir = src.read(1).astype(np.float32)
        red = src.read(2).astype(np.float32)
        profile = src.profile.copy()

    # Compute NDVI with epsilon to avoid division by zero
    denominator = nir + red
    # Where both bands are 0 (nodata areas), set denominator to 1 to avoid warning
    denominator = np.where(denominator == 0, 1, denominator)
    ndvi = (nir - red) / denominator

    # Set nodata where both bands were 0
    nodata_mask = (nir == 0) & (red == 0)
    ndvi[nodata_mask] = -9999

    # Clip to valid range (should already be -1 to 1, but ensure)
    ndvi = np.clip(ndvi, -1, 1)
    ndvi[nodata_mask] = -9999  # Re-apply after clip

    # Update profile for single-band float output
    profile.update(
        count=1,
        dtype=np.float32,
        nodata=-9999,
    )

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(ndvi, 1)

    # Compute statistics (excluding nodata)
    valid_mask = ~nodata_mask
    valid_ndvi = ndvi[valid_mask]

    stats = {
        "min": float(np.min(valid_ndvi)),
        "max": float(np.max(valid_ndvi)),
        "mean": float(np.mean(valid_ndvi)),
        "std": float(np.std(valid_ndvi)),
        "vegetation_pixels": int(np.sum(valid_ndvi > 0.3)),
        "total_valid_pixels": int(np.sum(valid_mask)),
        "vegetation_fraction": float(np.sum(valid_ndvi > 0.3) / np.sum(valid_mask)),
    }

    return stats


def clean_ndvi(city: str, neighbourhood: str) -> RasterCleaningLog:
    """Compute NDVI for a neighbourhood from CIR orthophoto.

    Returns RasterCleaningLog with processing details.
    """
    started_at = datetime.now(timezone.utc)

    base_path = neighbourhood_path(city, neighbourhood)

    # Find CIR orthophoto in raw/
    raw_path = base_path / "raw"
    cir_files = list(raw_path.glob("orthophoto_cir_*.tif"))
    if not cir_files:
        raise FileNotFoundError(f"No CIR orthophoto found in {raw_path}")

    # Use most recent
    cir_path = sorted(cir_files)[-1]
    print(f"Using CIR orthophoto: {cir_path.name}")

    # Output path
    output_path = base_path / "cleaned" / "ndvi.tif"

    print(f"Computing NDVI...")
    stats = compute_ndvi(cir_path, output_path)

    print(f"  NDVI range: [{stats['min']:.3f}, {stats['max']:.3f}]")
    print(f"  Mean NDVI: {stats['mean']:.3f}")
    print(f"  Vegetation pixels (NDVI > 0.3): {stats['vegetation_pixels']:,}")
    print(f"  Vegetation fraction: {stats['vegetation_fraction']:.1%}")

    finished_at = datetime.now(timezone.utc)

    # Create cleaning log
    log = RasterCleaningLog(
        dataset="ndvi",
        raw_input_path=str(cir_path),
        cleaned_output_path=str(output_path),
        started_at=started_at,
        finished_at=finished_at,
        crs="EPSG:31370",
        resolution_m=0.4,  # Same as source CIR
        decisions=[
            "NDVI = (NIR - Red) / (NIR + Red)",
            "CIR bands: NIR=1, Red=2, Green=3",
            "Nodata set to -9999 where both bands were 0",
            "Vegetation threshold for stats: NDVI > 0.3",
            f"Vegetation pixels (NDVI > 0.3): {stats['vegetation_pixels']:,}",
            f"Vegetation fraction: {stats['vegetation_fraction']:.1%}",
        ],
    )

    # Write log
    log.save(output_path.parent / "ndvi_cleaning_log.yaml")

    print(f"Saved to {output_path}")
    return log


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute NDVI from CIR orthophoto")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    clean_ndvi(args.city, args.neighbourhood)
