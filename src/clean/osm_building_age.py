"""Join OSM building construction years to buildings dataset.

Spatially joins OSM building:year tags to existing buildings based on
footprint overlap. OSM data is sparse but can provide construction dates
where available.

Adds column:
- construction_year: Year building was constructed (from OSM, nullable)

Decisions:
- Spatial join based on largest overlap (buildings can be subdivided in cadastre)
- Only assign year if overlap > 50% of building footprint
- Keep null for buildings with no OSM match (most buildings)

Usage:
    python -m src.clean.osm_building_age antwerp haringrode
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import geopandas as gpd
import numpy as np

from src.clean._common import CleaningLog
from src.ingest._common import neighbourhood_path


def join_osm_building_ages(city: str, neighbourhood: str) -> CleaningLog:
    """Join OSM construction years to buildings.

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

    # Load OSM building ages
    osm_path = base / "raw" / "osm_building_age.gpkg"
    if not osm_path.exists():
        raise FileNotFoundError(f"OSM building age data not found at {osm_path}")

    osm = gpd.read_file(osm_path)

    print(f"Loaded {len(buildings)} buildings and {len(osm)} OSM buildings with construction years")

    # Start cleaning log
    log = CleaningLog(
        dataset="osm_building_age",
        raw_input_path=str(osm_path),
        cleaned_output_path=str(buildings_path),
        started_at=now,
    )
    log.rows_in = len(osm)

    if len(osm) == 0:
        print("  No OSM data available - setting all construction_year to null")
        buildings["construction_year"] = None
        log.rows_out = 0
        log.decisions.append("No OSM building age data available for this area")
    else:
        # Spatial join: find best matching OSM building for each cadastral building
        print("  Computing spatial overlaps...")

        construction_years = []

        for idx, building in buildings.iterrows():
            # Find overlapping OSM buildings
            overlaps = osm[osm.intersects(building.geometry)]

            if len(overlaps) == 0:
                construction_years.append(None)
                continue

            # Compute overlap areas
            overlap_areas = overlaps.geometry.intersection(building.geometry).area
            building_area = building.geometry.area

            # Find best match (largest overlap)
            best_idx = overlap_areas.idxmax()
            best_overlap_ratio = overlap_areas[best_idx] / building_area

            # Only assign if overlap > 50%
            if best_overlap_ratio > 0.5:
                construction_years.append(overlaps.loc[best_idx, "construction_year"])
            else:
                construction_years.append(None)

        buildings["construction_year"] = construction_years

        # Stats
        matched = sum(1 for y in construction_years if y is not None)
        print(f"\n  Matched {matched}/{len(buildings)} buildings to OSM data ({matched/len(buildings)*100:.1f}%)")

        if matched > 0:
            years = [y for y in construction_years if y is not None]
            print(f"  Construction year range: {min(years)} - {max(years)}")
            print(f"  Median: {int(np.median(years))}")

        log.rows_out = matched
        log.decisions.append("Spatial join based on largest footprint overlap")
        log.decisions.append("Only assign year if overlap > 50% of building area")
        log.decisions.append(f"Matched {matched}/{len(buildings)} buildings ({matched/len(buildings)*100:.1f}%)")

    log.columns_added.append("construction_year")

    # Save back to buildings
    print(f"\n  Saving updated buildings to {buildings_path}...")
    buildings.to_file(buildings_path, driver="GPKG")

    # Finalize log
    log.finished_at = datetime.now(timezone.utc)
    log.save()

    print(f"\nDone! Construction years added to buildings")
    print(f"Cleaning log: {buildings_path}.cleaning_log.yaml")

    return log


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Join OSM building ages to buildings")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    join_osm_building_ages(args.city, args.neighbourhood)
