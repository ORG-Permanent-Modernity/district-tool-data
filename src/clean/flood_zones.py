"""Clean flood zone (watertoets advisory) data.

Processes raw flood-prone areas from the watertoets advisory map.

Cleaning steps:
- Normalize flood risk codes (VMM, DVW) to categories
- Extract relevant attributes (capakey, province, municipality)
- Classify risk levels based on code combinations
- Clip to AOI

Decisions:
- VMM codes: V0101 = fluvial flood risk
- DVW codes: V0031/V0060 = coastal/waterways flood risk
- Risk level: high if multiple codes, moderate if single code, low if no codes
- CAPAKEY preserved for parcel linkage

Usage:
    python -m src.clean.flood_zones antwerp haringrode
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import geopandas as gpd

from src.clean._common import CleaningLog
from src.ingest._common import load_aoi, neighbourhood_path


def clean_flood_zones(city: str, neighbourhood: str) -> CleaningLog:
    """Clean flood zone data.

    Args:
        city: City name
        neighbourhood: Neighbourhood name

    Returns:
        CleaningLog with details of what was done.
    """
    now = datetime.now(timezone.utc)
    base = neighbourhood_path(city, neighbourhood)

    # Find the most recent raw file
    raw_dir = base / "raw"
    raw_files = list(raw_dir.glob("flood_zones_*.gpkg"))
    if not raw_files:
        raise FileNotFoundError(f"No flood zones found in {raw_dir}")

    raw_path = max(raw_files)  # Most recent by name
    print(f"Loading {raw_path}...")

    flood_zones = gpd.read_file(raw_path)

    # Start cleaning log
    log = CleaningLog(
        dataset="flood_zones",
        raw_input_path=str(raw_path),
        cleaned_output_path=str(base / "cleaned" / "flood_zones.gpkg"),
        started_at=now,
    )
    log.rows_in = len(flood_zones)
    print(f"Loaded {len(flood_zones)} flood zone polygons")

    # Normalize column names
    column_map = {
        "GmlID": "source_id",
        "CAPAKEY": "capakey",
        "prov": "province",
        "gem": "municipality",
        "VMM": "vmm_code",
        "DVW": "dvw_code",
        "haven": "harbor_code",
        "MDK": "mdk_code",
        "penw": "penw_code",
    }

    existing_cols = {k: v for k, v in column_map.items() if k in flood_zones.columns}
    flood_zones = flood_zones[list(existing_cols.keys()) + ["geometry"]].copy()
    flood_zones = flood_zones.rename(columns=existing_cols)

    log.columns_renamed.update(existing_cols)

    # Clean code columns (replace ' ' with None)
    code_cols = ["vmm_code", "dvw_code", "harbor_code", "mdk_code", "penw_code"]
    for col in code_cols:
        if col in flood_zones.columns:
            flood_zones[col] = flood_zones[col].replace(" ", None)

    # Classify flood risk type and level
    def classify_flood_risk(row):
        """Classify flood risk based on code combinations."""
        codes = []
        if row.get("vmm_code"):
            codes.append("fluvial")  # VMM codes = river/stream flooding
        if row.get("dvw_code"):
            codes.append("coastal_waterways")  # DVW codes = coastal/major waterways
        if row.get("harbor_code"):
            codes.append("harbor")
        if row.get("mdk_code"):
            codes.append("climate")
        if row.get("penw_code"):
            codes.append("penw")

        if len(codes) == 0:
            return "none", "low"
        elif len(codes) == 1:
            return codes[0], "moderate"
        else:
            return "+".join(codes), "high"

    flood_zones[["risk_type", "risk_level"]] = flood_zones.apply(
        lambda row: pd.Series(classify_flood_risk(row)), axis=1
    )

    log.columns_added.extend(["risk_type", "risk_level"])
    log.decisions.append("risk_type classified from VMM/DVW codes: fluvial, coastal_waterways, etc.")
    log.decisions.append("risk_level: high (multiple codes), moderate (single code), low (no codes)")

    # Compute area
    flood_zones["area_m2"] = flood_zones.geometry.area
    log.columns_added.append("area_m2")

    # Clip to AOI (strict boundary)
    aoi = load_aoi(city, neighbourhood)
    before = len(flood_zones)
    flood_zones = gpd.clip(flood_zones, aoi)
    dropped_outside = before - len(flood_zones)

    if dropped_outside > 0:
        log.rows_dropped["outside AOI"] = dropped_outside
        print(f"Clipped to AOI: dropped {dropped_outside} polygons outside boundary")

    # Save to cleaned
    cleaned_dir = base / "cleaned"
    cleaned_dir.mkdir(parents=True, exist_ok=True)
    cleaned_path = cleaned_dir / "flood_zones.gpkg"

    print(f"\nSaving to {cleaned_path}...")
    flood_zones.to_file(cleaned_path, driver="GPKG")

    # Finalize log
    log.rows_out = len(flood_zones)
    log.finished_at = datetime.now(timezone.utc)
    log.save()

    print(f"\nDone! {len(flood_zones)} flood zones cleaned")
    print(f"Cleaning log: {cleaned_path}.cleaning_log.yaml")

    # Show risk breakdown
    print(f"\nRisk level breakdown:")
    print(flood_zones["risk_level"].value_counts())
    print(f"\nRisk type breakdown:")
    print(flood_zones["risk_type"].value_counts())

    return log


if __name__ == "__main__":
    import pandas as pd  # Needed for pd.Series in classify_flood_risk

    parser = argparse.ArgumentParser(description="Clean flood zone data")
    parser.add_argument("city", help="City name (e.g., antwerp)")
    parser.add_argument("neighbourhood", help="Neighbourhood name (e.g., haringrode)")
    args = parser.parse_args()

    clean_flood_zones(args.city, args.neighbourhood)
