"""Enrich sectors with demographic data from Statbel.

Joins multiple demographic datasets to statistical sectors:
- Income (2023) - median, average, distribution
- Car ownership (2022) - households, cars
- Age distribution by sex (Census 2021)
- Dwelling types (Census 2021)

Decisions:
- Income data from 2023 (most recent fiscal year)
- Car data from 2022 (most recent available)
- Census 2021 for age/sex and dwellings
- Age/sex data pivoted to wide format (age_0_4_m, age_0_4_f, etc.)
- Employment, education, household composition NOT available at sector level

Usage:
    python -m src.clean.sectors_demographics antwerp haringrode
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd

from src.clean._common import CleaningLog
from src.ingest._common import neighbourhood_path


def enrich_sectors_demographics(city: str, neighbourhood: str) -> CleaningLog:
    """Enrich sectors with demographic data.

    Args:
        city: City name
        neighbourhood: Neighbourhood name

    Returns:
        CleaningLog with details of what was done.
    """
    now = datetime.now(timezone.utc)
    base = neighbourhood_path(city, neighbourhood)
    shared = Path("/Users/loucas/Documents/ORG/things too big for git/DISTRICT/shared")

    # Load base sectors
    sectors_path = base / "reviewed" / "sectors.gpkg"
    sectors = gpd.read_file(sectors_path)

    # Output path
    cleaned_path = base / "cleaned" / "sectors.gpkg"

    # Start cleaning log
    log = CleaningLog(
        dataset="sectors_demographics",
        raw_input_path=str(sectors_path),
        cleaned_output_path=str(cleaned_path),
        started_at=now,
    )
    log.rows_in = len(sectors)
    print(f"Loaded {len(sectors)} sectors from {sectors_path}")

    # ========== 1. JOIN INCOME DATA (2023) ==========
    print("\n=== Joining income data (2023) ===")
    income = pd.read_excel(shared / "statbel_income_2023.xlsx")

    # Filter to 2023 only
    income_2023 = income[income['CD_YEAR'] == 2023].copy()
    print(f"  Loaded {len(income_2023)} income records for 2023")

    # Join on sector code
    income_cols = {
        'CD_SECTOR': 'source_id',  # Join key
        'MS_MEDIAN_NET_TAXABLE_INC': 'income_median_eur',
        'MS_AVG_TOT_NET_TAXABLE_INC': 'income_mean_eur',
        'MS_NBR_NON_ZERO_INC': 'income_declarations',
    }
    income_subset = income_2023[list(income_cols.keys())].rename(columns=income_cols)

    sectors = sectors.merge(income_subset, on='source_id', how='left')
    n_matched = sectors['income_median_eur'].notna().sum()
    print(f"  Matched {n_matched}/{len(sectors)} sectors")
    log.columns_added.extend(['income_median_eur', 'income_mean_eur', 'income_declarations'])
    log.decisions.append(f"Income data from 2023 joined on source_id ({n_matched} matches)")

    # ========== 2. JOIN CAR OWNERSHIP (2022) ==========
    print("\n=== Joining car ownership data (2022) ===")
    cars = pd.read_excel(shared / "statbel_cars_household_2022.xlsx")

    # Filter to 2022 only
    cars_2022 = cars[cars['CD_YEAR'] == 2022].copy()
    print(f"  Loaded {len(cars_2022)} car records for 2022")

    # Join on sector code
    cars_cols = {
        'cd_sector': 'source_id',  # Join key (note lowercase in this dataset)
        'total_huisH': 'households_total',
        'total_wagens': 'cars_total',
    }
    cars_subset = cars_2022[list(cars_cols.keys())].rename(columns=cars_cols)

    sectors = sectors.merge(cars_subset, on='source_id', how='left')

    # Compute cars per household
    sectors['cars_per_household'] = sectors['cars_total'] / sectors['households_total']

    n_matched = sectors['households_total'].notna().sum()
    print(f"  Matched {n_matched}/{len(sectors)} sectors")
    log.columns_added.extend(['households_total', 'cars_total', 'cars_per_household'])
    log.decisions.append(f"Car ownership from 2022 joined on source_id ({n_matched} matches)")
    log.decisions.append("cars_per_household computed as cars_total / households_total")

    # ========== 3. JOIN AGE + SEX (CENSUS 2021) ==========
    print("\n=== Joining age + sex data (Census 2021) ===")
    census_age_sex = pd.read_excel(shared / "statbel_census_2021_age_sex.xlsx")
    print(f"  Loaded {len(census_age_sex)} age/sex records")

    # Pivot age groups by sex
    # Create column names like: age_0_4_male, age_0_4_female, age_0_4_total
    age_pivot = census_age_sex.pivot_table(
        index='CD_SECTOR',
        columns=['CD_SEX', 'CD_AGE'],
        values='MS_POP',
        aggfunc='sum',
        fill_value=0
    )

    # Flatten column names
    age_pivot.columns = [f'pop_{age}_{sex.lower()}' for sex, age in age_pivot.columns]
    age_pivot = age_pivot.reset_index()
    age_pivot.columns = age_pivot.columns.str.replace('-', '_').str.replace('+', 'plus')

    # Also compute age group totals (M + F)
    age_groups = census_age_sex['CD_AGE'].unique()
    for age in age_groups:
        age_clean = age.replace('-', '_').replace('+', 'plus')
        male_col = f'pop_{age_clean}_m'
        female_col = f'pop_{age_clean}_f'
        total_col = f'pop_{age_clean}_total'
        if male_col in age_pivot.columns and female_col in age_pivot.columns:
            age_pivot[total_col] = age_pivot[male_col] + age_pivot[female_col]

    # Rename join key
    age_pivot = age_pivot.rename(columns={'CD_SECTOR': 'source_id'})

    # Join to sectors
    sectors = sectors.merge(age_pivot, on='source_id', how='left')

    n_age_cols = len([c for c in age_pivot.columns if c.startswith('pop_')])
    print(f"  Added {n_age_cols} age/sex columns")
    log.columns_added.extend([c for c in age_pivot.columns if c != 'source_id'])
    log.decisions.append(f"Age/sex distribution from Census 2021 pivoted to wide format ({n_age_cols} columns)")

    # ========== 4. JOIN DWELLING TYPES (CENSUS 2021) ==========
    print("\n=== Joining dwelling types (Census 2021) ===")
    dwellings = pd.read_excel(shared / "statbel_census_2021_households.xlsx")
    print(f"  Loaded {len(dwellings)} dwelling records")

    # Pivot dwelling types
    dwelling_pivot = dwellings.pivot_table(
        index='CD_SECTOR',
        columns='CD_TLQ',
        values='MS_LOGEMENTS',
        aggfunc='sum',
        fill_value=0
    )

    # Rename columns for clarity
    dwelling_cols_map = {
        'DW_OC': 'dwellings_conventional',
        'CLQ': 'dwellings_collective',
        'H_OTH': 'dwellings_other',
    }
    dwelling_pivot = dwelling_pivot.rename(columns=dwelling_cols_map)
    dwelling_pivot['dwellings_total'] = dwelling_pivot.sum(axis=1)
    dwelling_pivot = dwelling_pivot.reset_index().rename(columns={'CD_SECTOR': 'source_id'})

    # Join to sectors
    sectors = sectors.merge(dwelling_pivot, on='source_id', how='left')

    n_matched = sectors['dwellings_total'].notna().sum()
    print(f"  Matched {n_matched}/{len(sectors)} sectors")
    log.columns_added.extend(list(dwelling_cols_map.values()) + ['dwellings_total'])
    log.decisions.append(f"Dwelling types from Census 2021 joined on source_id ({n_matched} matches)")

    # ========== SAVE ==========
    print(f"\nSaving enriched sectors to {cleaned_path}...")
    cleaned_path.parent.mkdir(parents=True, exist_ok=True)
    sectors.to_file(cleaned_path, driver="GPKG")

    # Finalize log
    log.rows_out = len(sectors)
    log.finished_at = datetime.now(timezone.utc)
    log.anomalies.append("Employment, education, household composition NOT available at sector level (privacy constraints)")
    log.save()

    print(f"\nDone! Added {len(log.columns_added)} demographic columns")
    print(f"Cleaning log saved to {cleaned_path}.cleaning_log.yaml")

    return log


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enrich sectors with demographic data")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    enrich_sectors_demographics(args.city, args.neighbourhood)
