"""Clean Antwerp tree inventory for a neighbourhood.

This script processes the Antwerp public tree inventory:
- Maps Latin species name to species column
- Derives diameter_class from STAMOMTREK (trunk circumference)
- Estimates crown radius from trunk circumference
- Adds stable UUIDs

Decisions:
- species: LATBOOMSOORT (Latin name with cultivar)
- common_name: set to null (not in source data)
- planted_year: set to null (not in source data)
- diameter_class: derived from STAMOMTREK using standard ranges
- estimated_crown_radius_m: empirically derived from trunk circumference

Crown radius estimation:
  Trunk circumference (cm) -> trunk diameter (cm) -> crown radius (m)
  Using rule of thumb: crown diameter ≈ trunk diameter (cm) * 0.1 (for mature urban trees)
  Crown radius = crown diameter / 2
  With minimum of 2.5m for small/young trees

Usage:
    python -m src.clean.trees antwerp haringrode
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np

from src.clean._common import CleaningLog, stable_uuid
from src.ingest._common import neighbourhood_path


def circumference_to_diameter_class(circumference_cm: float | None) -> str | None:
    """Convert trunk circumference to diameter class."""
    if circumference_cm is None or np.isnan(circumference_cm):
        return None
    diameter_cm = circumference_cm / np.pi
    if diameter_cm < 10:
        return "<10cm"
    elif diameter_cm < 20:
        return "10-20cm"
    elif diameter_cm < 40:
        return "20-40cm"
    elif diameter_cm < 60:
        return "40-60cm"
    elif diameter_cm < 80:
        return "60-80cm"
    else:
        return ">80cm"


def estimate_crown_radius(circumference_cm: float | None, min_radius: float = 2.5) -> float:
    """Estimate crown radius from trunk circumference.

    Uses empirical relationship for urban trees.
    Returns minimum radius for small/unknown trees.
    """
    if circumference_cm is None or np.isnan(circumference_cm) or circumference_cm <= 0:
        return min_radius

    # Trunk diameter in cm
    trunk_diameter_cm = circumference_cm / np.pi

    # Crown diameter roughly 8-12x trunk diameter for mature trees
    # Use 10x as middle estimate, but this varies by species
    crown_diameter_m = trunk_diameter_cm * 0.10

    # Crown radius
    crown_radius = crown_diameter_m / 2

    # Apply minimum
    return max(crown_radius, min_radius)


def clean_trees(city: str, neighbourhood: str) -> CleaningLog:
    """Clean trees for a neighbourhood.

    Returns the CleaningLog with details of what was done.
    """
    now = datetime.now(timezone.utc)
    base = neighbourhood_path(city, neighbourhood)

    # Find raw input
    raw_candidates = sorted(base.glob("raw/antwerp_trees_*.gpkg"), reverse=True)
    if not raw_candidates:
        raise FileNotFoundError(f"No raw tree data found in {base}/raw/")
    raw_path = raw_candidates[0]

    # Output path
    cleaned_path = base / "cleaned" / "trees.gpkg"

    # Start cleaning log
    log = CleaningLog(
        dataset="trees",
        raw_input_path=str(raw_path),
        cleaned_output_path=str(cleaned_path),
        started_at=now,
    )

    # Load raw data
    print(f"Loading raw trees from {raw_path}...")
    gdf = gpd.read_file(raw_path)
    log.rows_in = len(gdf)
    print(f"  Loaded {len(gdf)} features")

    # Map species
    print("Mapping species...")
    gdf["species"] = gdf["LATBOOMSOORT"]
    n_with_species = gdf["species"].notna().sum()
    log.columns_added.append("species")
    log.decisions.append("species from LATBOOMSOORT (Latin name with cultivar)")
    print(f"  {n_with_species} trees with species, {len(gdf) - n_with_species} unknown")

    # Common name - not available
    gdf["common_name"] = None
    log.columns_added.append("common_name")
    log.decisions.append("common_name set to null (not in source data)")

    # Planted year - not available
    gdf["planted_year"] = None
    log.columns_added.append("planted_year")
    log.decisions.append("planted_year set to null (not in source data)")

    # Diameter class from trunk circumference
    print("Computing diameter class...")
    gdf["diameter_class"] = gdf["STAMOMTREK"].apply(circumference_to_diameter_class)
    n_with_diameter = gdf["diameter_class"].notna().sum()
    log.columns_added.append("diameter_class")
    log.decisions.append("diameter_class derived from STAMOMTREK (trunk circumference)")
    print(f"  {n_with_diameter} trees with diameter class")

    # Diameter class distribution
    class_counts = gdf["diameter_class"].value_counts().to_dict()
    print(f"  Distribution: {class_counts}")

    # Estimate crown radius
    print("Estimating crown radius...")
    gdf["estimated_crown_radius_m"] = gdf["STAMOMTREK"].apply(estimate_crown_radius)
    log.columns_added.append("estimated_crown_radius_m")
    log.decisions.append(
        "estimated_crown_radius_m from trunk circumference "
        "(crown diameter ≈ trunk diameter * 0.1, min 2.5m)"
    )
    mean_radius = gdf["estimated_crown_radius_m"].mean()
    print(f"  Mean crown radius: {mean_radius:.1f}m")

    # Add stable UUIDs
    print("Adding stable UUIDs...")
    gdf["id"] = [stable_uuid() for _ in range(len(gdf))]
    gdf["source_id"] = gdf["OBJECTID"].astype(str)
    log.columns_added.extend(["id", "source_id"])

    # Select final columns
    final_cols = [
        "id",
        "source_id",
        "geometry",
        "species",
        "common_name",
        "planted_year",
        "diameter_class",
        "estimated_crown_radius_m",
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

    print(f"\nDone! {log.rows_in} -> {log.rows_out} trees")
    print(f"Cleaning log saved to {cleaned_path}.cleaning_log.yaml")

    return log


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean Antwerp tree inventory")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    clean_trees(args.city, args.neighbourhood)
