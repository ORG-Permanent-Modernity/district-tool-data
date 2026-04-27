"""Shared utilities for ingest scripts.

Every ingest script in src/ingest/<dataset>.py uses helpers from here for:
- Reading the AOI for a given (city, neighbourhood)
- Resolving the catalogue endpoint
- Writing the dated raw output
- Appending a row to _ingest_log.yaml

Implementations to be filled in. The functions below are stubs documenting
the intended interface.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import yaml

# Read DATA_ROOT from environment via pydantic-settings or python-dotenv.
# Implementation TBD — see src/data/loader.py for the same pattern.


def get_data_root() -> Path:
    """Return the configured data root, raising if unset."""
    raise NotImplementedError


def neighbourhood_path(city: str, neighbourhood: str) -> Path:
    """Return the path to a neighbourhood's data folder."""
    return get_data_root() / city / neighbourhood


def load_aoi(city: str, neighbourhood: str) -> gpd.GeoDataFrame:
    """Load the AOI polygon for a neighbourhood. Raises if missing."""
    raise NotImplementedError


def aoi_bbox(
    city: str,
    neighbourhood: str,
    buffer_m: float = 0,
) -> tuple[float, float, float, float]:
    """Return (minx, miny, maxx, maxy) of the AOI, optionally buffered.

    Always in EPSG:31370.
    """
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError


def assert_crs_31370(gdf: gpd.GeoDataFrame) -> None:
    """Raise if the GeoDataFrame is not in EPSG:31370.

    Use after reading a source: if the source isn't 31370, reproject explicitly.
    """
    if gdf.crs is None or gdf.crs.to_epsg() != 31370:
        raise ValueError(
            f"Expected EPSG:31370, got {gdf.crs}. "
            "Reproject explicitly during ingest."
        )
