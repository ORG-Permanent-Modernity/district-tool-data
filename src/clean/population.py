"""Join Statbel population data to statistical sectors.

This script reads the cleaned sectors GeoPackage and joins population data
from the Statbel population-by-sector CSV/TXT file.

Source data:
    https://statbel.fgov.be/en/open-data/population-statistical-sector-2024

The population file should be at:
    $DATA_ROOT/shared/statbel_population_<year>.txt

Output:
    Updates cleaned/sectors.gpkg with population column, OR
    Creates cleaned/sectors_with_pop.gpkg

Usage:
    python -m src.clean.population antwerp haringrode --pop-year 2024
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd

from src.clean._common import CleaningLog
from src.ingest._common import get_data_root, neighbourhood_path


def join_population(
    city: str,
    neighbourhood: str,
    pop_year: int = 2024,
) -> CleaningLog:
    """Join population data to cleaned sectors.

    Returns the CleaningLog with details of what was done.
    """
    now = datetime.now(timezone.utc)
    base = neighbourhood_path(city, neighbourhood)
    data_root = get_data_root()

    # Find population source
    pop_path = data_root / "shared" / f"statbel_population_{pop_year}.txt"
    if not pop_path.exists():
        raise FileNotFoundError(
            f"Population data not found at {pop_path}.\n\n"
            f"Download from: https://statbel.fgov.be/en/open-data/population-statistical-sector-{pop_year}\n"
            f"Extract and save as: {pop_path}"
        )

    # Find cleaned sectors
    sectors_path = base / "cleaned" / "sectors.gpkg"
    if not sectors_path.exists():
        raise FileNotFoundError(
            f"Cleaned sectors not found at {sectors_path}.\n"
            "Run src.clean.sectors first."
        )

    # Output path (overwrites sectors with population added)
    output_path = sectors_path

    # Start cleaning log
    log = CleaningLog(
        dataset="sectors_population",
        raw_input_path=str(pop_path),
        cleaned_output_path=str(output_path),
        started_at=now,
    )

    # Load sectors
    print(f"Loading cleaned sectors from {sectors_path}...")
    gdf = gpd.read_file(sectors_path)
    log.rows_in = len(gdf)
    print(f"  Loaded {len(gdf)} sectors")

    # Load population data
    print(f"Loading population data from {pop_path}...")
    # File is pipe-delimited with BOM
    pop_df = pd.read_csv(pop_path, sep="|", encoding="utf-8-sig")
    print(f"  Loaded {len(pop_df)} population records")
    print(f"  Columns: {list(pop_df.columns)}")

    # The sector code in population file is CD_SECTOR
    # We need to match to source_id in our sectors
    # CD_SECTOR format: "11001A00-" (municipality NIS + sector suffix)

    # Create lookup dict
    pop_lookup = dict(zip(pop_df["CD_SECTOR"].astype(str), pop_df["TOTAL"]))

    # Join population to sectors
    print("Joining population to sectors...")
    gdf["population"] = gdf["source_id"].map(pop_lookup)

    n_matched = gdf["population"].notna().sum()
    n_unmatched = len(gdf) - n_matched

    print(f"  Matched: {n_matched}, Unmatched: {n_unmatched}")

    if n_unmatched > 0:
        unmatched_ids = gdf[gdf["population"].isna()]["source_id"].tolist()
        log.anomalies.append(f"{n_unmatched} sectors without population data: {unmatched_ids[:5]}...")

    # Calculate population density
    gdf["pop_density_per_km2"] = gdf.apply(
        lambda row: (row["population"] / row["area_m2"] * 1_000_000)
        if row["population"] is not None and row["area_m2"] > 0
        else None,
        axis=1,
    )

    log.columns_added.extend(["population", "pop_density_per_km2"])
    log.decisions.append(f"population joined from statbel_population_{pop_year}.txt")
    log.decisions.append("pop_density_per_km2 = population / area_m2 * 1,000,000")

    # Summary stats
    total_pop = gdf["population"].sum()
    mean_density = gdf["pop_density_per_km2"].mean()
    print(f"  Total population in AOI: {total_pop:,.0f}")
    print(f"  Mean density: {mean_density:,.0f} per km²")

    # Save (overwrite original)
    print(f"Saving to {output_path}...")
    gdf.to_file(output_path, driver="GPKG")

    # Finalize log
    log.rows_out = len(gdf)
    log.finished_at = datetime.now(timezone.utc)
    log.save()

    print(f"\nDone! Population joined to {log.rows_out} sectors")
    print(f"Cleaning log saved to {output_path}.cleaning_log.yaml")

    return log


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Join Statbel population to sectors")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    parser.add_argument(
        "--pop-year",
        type=int,
        default=2024,
        help="Year of the population data (default: 2024)",
    )
    args = parser.parse_args()

    join_population(args.city, args.neighbourhood, args.pop_year)
