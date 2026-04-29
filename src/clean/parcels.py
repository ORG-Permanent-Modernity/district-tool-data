"""Clean cadastral parcels data.

Normalizes GRB Administratief Perceel (ADP) data and clips to AOI.

Adds columns:
- id: Stable UUID
- source_id: GRB parcel identifier
- area_m2: Parcel area in square meters

Decisions:
- Strict AOI clipping (no buffer - parcels define property boundaries)
- Invalid geometries fixed with make_valid
- Minimum parcel size: none (keep all parcels, even slivers from clipping)
- CAPAKEY preserved where available (cadastral key)

Usage:
    python -m src.clean.parcels antwerp haringrode
"""
from __future__ import annotations

import argparse
import uuid
from datetime import datetime, timezone

import geopandas as gpd

from src.clean._common import CleaningLog
from src.ingest._common import load_aoi, neighbourhood_path


def clean_parcels(city: str, neighbourhood: str) -> CleaningLog:
    """Clean cadastral parcels data.

    Args:
        city: City name
        neighbourhood: Neighbourhood name

    Returns:
        CleaningLog with details of what was done.
    """
    now = datetime.now(timezone.utc)
    base = neighbourhood_path(city, neighbourhood)

    # Find most recent raw file
    raw_dir = base / "raw"
    raw_files = sorted(raw_dir.glob("parcels_*.gpkg"))
    if not raw_files:
        raise FileNotFoundError(f"No raw parcels files found in {raw_dir}")

    raw_path = raw_files[-1]
    print(f"Loading {len(gpd.read_file(raw_path))} parcels from {raw_path}...")

    # Load raw data
    parcels = gpd.read_file(raw_path)

    # Start cleaning log
    log = CleaningLog(
        dataset="parcels",
        raw_input_path=str(raw_path),
        cleaned_output_path=str(base / "cleaned" / "parcels.gpkg"),
        started_at=now,
    )
    log.rows_in = len(parcels)

    # Load AOI for strict clipping
    aoi = load_aoi(city, neighbourhood)

    # Fix invalid geometries
    invalid_count = (~parcels.geometry.is_valid).sum()
    if invalid_count > 0:
        print(f"  Fixing {invalid_count} invalid geometries...")
        parcels.geometry = parcels.geometry.make_valid()
        log.decisions.append(f"Fixed {invalid_count} invalid geometries with make_valid()")

    # Clip to strict AOI
    print(f"  Clipping to AOI...")
    parcels_clipped = parcels[parcels.intersects(aoi.union_all())].copy()
    dropped = len(parcels) - len(parcels_clipped)
    if dropped > 0:
        log.rows_dropped["outside_aoi"] = dropped

    print(f"  Kept {len(parcels_clipped)} parcels within AOI (dropped {dropped})")

    # Normalize columns
    print(f"  Normalizing columns...")

    # Keep GRB identifier as source_id (usually OIDN)
    if "OIDN" in parcels_clipped.columns:
        parcels_clipped["source_id"] = parcels_clipped["OIDN"].astype(str)
    elif "oidn" in parcels_clipped.columns:
        parcels_clipped["source_id"] = parcels_clipped["oidn"].astype(str)
    else:
        # Fallback: use row index
        parcels_clipped["source_id"] = [f"parcel_{i}" for i in range(len(parcels_clipped))]
        log.decisions.append("No OIDN column found - generated source_id from row index")

    # Add stable UUID as primary ID
    parcels_clipped["id"] = [str(uuid.uuid4()) for _ in range(len(parcels_clipped))]

    # Preserve CAPAKEY if available (cadastral key format: XXXXX-X-XXXX-XX-XXX)
    if "CAPAKEY" in parcels_clipped.columns:
        parcels_clipped["capakey"] = parcels_clipped["CAPAKEY"].astype(str)
        parcels_clipped = parcels_clipped.drop(columns=["CAPAKEY"])
        log.columns_added.append("capakey")
    elif "capakey" in parcels_clipped.columns:
        # Already lowercase, keep it
        log.columns_added.append("capakey")

    # Compute area
    parcels_clipped["area_m2"] = parcels_clipped.geometry.area

    # Reorder columns: id, source_id, capakey (if exists), area_m2, geometry, then rest
    base_cols = ["id", "source_id"]
    if "capakey" in parcels_clipped.columns:
        base_cols.append("capakey")
    base_cols.append("area_m2")
    base_cols.append("geometry")

    other_cols = [c for c in parcels_clipped.columns if c not in base_cols]
    parcels_clipped = parcels_clipped[base_cols + other_cols]

    # Stats
    print(f"\n  Area statistics:")
    print(f"    Total area: {parcels_clipped['area_m2'].sum() / 10000:.2f} ha")
    print(f"    Mean parcel: {parcels_clipped['area_m2'].mean():.1f} m²")
    print(f"    Median parcel: {parcels_clipped['area_m2'].median():.1f} m²")
    print(f"    Range: {parcels_clipped['area_m2'].min():.1f} - {parcels_clipped['area_m2'].max():.1f} m²")

    # Save to cleaned
    cleaned_dir = base / "cleaned"
    cleaned_dir.mkdir(exist_ok=True)
    output_path = cleaned_dir / "parcels.gpkg"

    parcels_clipped.to_file(output_path, driver="GPKG")
    print(f"\n  Saved to {output_path}")

    # Finalize log
    log.rows_out = len(parcels_clipped)
    log.columns_added.extend(["id", "source_id", "area_m2"])
    log.finished_at = datetime.now(timezone.utc)
    log.decisions.append("Clipped to strict AOI (no buffer)")
    log.decisions.append("No minimum area threshold applied")
    log.save()

    print(f"\nDone! Cleaning log: {output_path}.cleaning_log.yaml")

    return log


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean cadastral parcels")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    clean_parcels(args.city, args.neighbourhood)
