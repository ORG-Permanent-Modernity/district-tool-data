"""Shared utilities for ingest scripts.

Every ingest script in src/ingest/<dataset>.py uses helpers from here for:
- Reading the AOI for a given (city, neighbourhood)
- Resolving the catalogue endpoint
- Writing the dated raw output
- Appending a row to _ingest_log.yaml
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import yaml
from dotenv import load_dotenv

load_dotenv()


def get_data_root() -> Path:
    """Return the configured data root, raising if unset."""
    raw = os.getenv("DATA_ROOT")
    if not raw:
        raise RuntimeError(
            "DATA_ROOT is not set. Add it to your .env file pointing "
            "at your data folder. Example:\n"
            "    DATA_ROOT=/path/to/district-tool-data"
        )
    path = Path(raw).expanduser().resolve()
    if not path.exists():
        raise RuntimeError(f"DATA_ROOT points at {path}, which does not exist.")
    return path


def neighbourhood_path(city: str, neighbourhood: str) -> Path:
    """Return the path to a neighbourhood's data folder."""
    return get_data_root() / city / neighbourhood


def load_aoi(city: str, neighbourhood: str) -> gpd.GeoDataFrame:
    """Load the AOI polygon for a neighbourhood. Raises if missing."""
    aoi_path = neighbourhood_path(city, neighbourhood) / "aoi.gpkg"
    if not aoi_path.exists():
        raise FileNotFoundError(
            f"AOI not found at {aoi_path}. "
            "Create the AOI polygon in QGIS before running ingest."
        )
    gdf = gpd.read_file(aoi_path)
    assert_crs_31370(gdf)
    return gdf


def aoi_bbox(
    city: str,
    neighbourhood: str,
    buffer_m: float = 0,
) -> tuple[float, float, float, float]:
    """Return (minx, miny, maxx, maxy) of the AOI, optionally buffered.

    Always in EPSG:31370.
    """
    aoi = load_aoi(city, neighbourhood)
    if buffer_m > 0:
        aoi = aoi.copy()
        aoi["geometry"] = aoi.geometry.buffer(buffer_m)
    bounds = aoi.total_bounds
    return (bounds[0], bounds[1], bounds[2], bounds[3])


def raw_output_path(
    city: str,
    neighbourhood: str,
    dataset: str,
    extension: str = "gpkg",
    date: datetime | None = None,
) -> Path:
    """Return the canonical raw output path for a dataset on a given date.

    Default date is today (UTC). Format: raw/<dataset>_<YYYY-MM-DD>.<ext>
    """
    if date is None:
        date = datetime.now(timezone.utc)
    date_str = date.strftime("%Y-%m-%d")
    base = neighbourhood_path(city, neighbourhood) / "raw"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{dataset}_{date_str}.{extension}"


def append_ingest_log(
    city: str,
    dataset: str,
    neighbourhood: str,
    *,
    started_at: datetime,
    finished_at: datetime,
    status: str,
    output_path: Path,
    rows_fetched: int | None = None,
    tiles_fetched: int | None = None,
    notes: str = "",
) -> None:
    """Append a run entry to _ingest_log.yaml at the city level."""
    log_path = get_data_root() / city / "_ingest_log.yaml"

    # Load existing log or create new
    if log_path.exists():
        with log_path.open() as f:
            log_data = yaml.safe_load(f) or {}
    else:
        log_data = {}

    if "runs" not in log_data:
        log_data["runs"] = []

    # Build the run entry
    run_id = f"{started_at.isoformat()}-{dataset}-{neighbourhood}"
    entry: dict[str, Any] = {
        "run_id": run_id,
        "dataset": dataset,
        "neighbourhood": neighbourhood,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "status": status,
        "output_path": str(output_path.relative_to(get_data_root())),
    }
    if rows_fetched is not None:
        entry["rows_fetched"] = rows_fetched
    if tiles_fetched is not None:
        entry["tiles_fetched"] = tiles_fetched
    if notes:
        entry["notes"] = notes

    log_data["runs"].append(entry)

    with log_path.open("w") as f:
        yaml.safe_dump(log_data, f, default_flow_style=False, sort_keys=False)


def assert_crs_31370(gdf: gpd.GeoDataFrame) -> None:
    """Raise if the GeoDataFrame is not in EPSG:31370.

    Use after reading a source: if the source isn't 31370, reproject explicitly.
    """
    if gdf.crs is None or gdf.crs.to_epsg() != 31370:
        raise ValueError(
            f"Expected EPSG:31370, got {gdf.crs}. "
            "Reproject explicitly during ingest."
        )
