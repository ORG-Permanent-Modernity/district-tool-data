"""Augment buildings with solar irradiance statistics.

Computes zonal statistics from solar irradiance raster for each building footprint.

Adds columns:
- solar_irradiation_kwh_m2: Mean rooftop irradiation (kWh/m²/year)
- solar_potential_kwh: Total annual potential (irradiation × roof_area × efficiency)
- solar_suitability: Categorical rating (excellent/good/moderate/poor)

Decisions:
- Mean irradiation within building footprint
- Efficiency factor: 0.15 (typical PV panel efficiency)
- Suitability thresholds: >1100=excellent, >900=good, >700=moderate, <=700=poor

Usage:
    python -m src.clean.buildings_solar antwerp haringrode
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.mask import mask

from src.clean._common import CleaningLog
from src.ingest._common import neighbourhood_path


def compute_building_solar_stats(city: str, neighbourhood: str) -> CleaningLog:
    """Augment buildings with solar irradiance statistics.

    Args:
        city: City name
        neighbourhood: Neighbourhood name

    Returns:
        CleaningLog with details of what was done.
    """
    now = datetime.now(timezone.utc)
    base = neighbourhood_path(city, neighbourhood)

    # Load buildings
    buildings_path = base / "reviewed" / "buildings.gpkg"
    buildings = gpd.read_file(buildings_path)

    # Load solar irradiance raster
    solar_path = base / "reviewed" / "solar_irradiance.tif"
    if not solar_path.exists():
        raise FileNotFoundError(f"Solar irradiance raster not found at {solar_path}")

    print(f"Loading {len(buildings)} buildings...")
    print(f"Loading solar irradiance from {solar_path}...")

    # Start cleaning log
    log = CleaningLog(
        dataset="buildings_solar",
        raw_input_path=str(buildings_path),
        cleaned_output_path=str(buildings_path),
        started_at=now,
    )
    log.rows_in = len(buildings)

    # Compute zonal stats
    print("Computing zonal statistics for each building...")

    solar_irradiation = []
    solar_potential = []

    with rasterio.open(solar_path) as src:
        for idx, building in buildings.iterrows():
            try:
                # Mask raster to building footprint
                geom = [building.geometry.__geo_interface__]
                out_image, out_transform = mask(src, geom, crop=True, nodata=-9999)

                # Get valid pixels (not nodata)
                valid_pixels = out_image[0][out_image[0] != -9999]

                if len(valid_pixels) > 0:
                    # Mean irradiation
                    mean_irrad = float(np.mean(valid_pixels))
                    solar_irradiation.append(mean_irrad)

                    # Total potential (kWh/year)
                    # = mean_irradiation (kWh/m²/year) × roof_area (m²) × efficiency (0.15)
                    roof_area = building['area_m2']
                    total_potential = mean_irrad * roof_area * 0.15
                    solar_potential.append(total_potential)
                else:
                    # No valid pixels (shouldn't happen, but handle gracefully)
                    solar_irradiation.append(None)
                    solar_potential.append(None)

            except Exception as e:
                print(f"  Warning: Failed to compute stats for building {building['id']}: {e}")
                solar_irradiation.append(None)
                solar_potential.append(None)

    # Add columns
    buildings['solar_irradiation_kwh_m2'] = solar_irradiation
    buildings['solar_potential_kwh'] = solar_potential

    # Classify suitability
    def classify_suitability(irrad):
        if irrad is None or np.isnan(irrad):
            return None
        elif irrad > 1100:
            return 'excellent'
        elif irrad > 900:
            return 'good'
        elif irrad > 700:
            return 'moderate'
        else:
            return 'poor'

    buildings['solar_suitability'] = buildings['solar_irradiation_kwh_m2'].apply(classify_suitability)

    log.columns_added.extend(['solar_irradiation_kwh_m2', 'solar_potential_kwh', 'solar_suitability'])

    # Stats
    valid_irrad = buildings['solar_irradiation_kwh_m2'].dropna()
    print(f"\nSolar irradiation statistics:")
    print(f"  Buildings with data: {len(valid_irrad)}/{len(buildings)}")
    print(f"  Range: {valid_irrad.min():.1f} - {valid_irrad.max():.1f} kWh/m²/year")
    print(f"  Mean: {valid_irrad.mean():.1f} kWh/m²/year")

    print(f"\nSuitability breakdown:")
    print(buildings['solar_suitability'].value_counts())

    # Save
    print(f"\nSaving augmented buildings to {buildings_path}...")
    buildings.to_file(buildings_path, driver="GPKG")

    # Finalize log
    log.rows_out = len(buildings)
    log.finished_at = datetime.now(timezone.utc)
    log.decisions.append("Computed mean irradiation within building footprint")
    log.decisions.append("solar_potential = irradiation × roof_area × 0.15 (PV efficiency)")
    log.decisions.append("Suitability: >1100=excellent, >900=good, >700=moderate, <=700=poor")
    log.save()

    print(f"\nDone! Solar stats added to buildings")
    print(f"Cleaning log: {buildings_path}.cleaning_log.yaml")

    return log


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Augment buildings with solar statistics")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    compute_building_solar_stats(args.city, args.neighbourhood)
