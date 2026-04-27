"""Shared utilities for cleaning scripts.

Every cleaning script in src/clean/<dataset>.py uses helpers from here for:
- The CleaningLog data structure (records what cleaning did)
- Common geometry validity fixes
- AOI clipping
- Stable UUID generation
- Writing cleaned output + log alongside

Implementations to be filled in.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import yaml


@dataclass
class CleaningLog:
    """Records what a cleaning script did. Saved alongside cleaned output."""

    dataset: str
    raw_input_path: str
    cleaned_output_path: str
    started_at: datetime
    finished_at: datetime | None = None

    rows_in: int = 0
    rows_out: int = 0
    rows_dropped: dict[str, int] = field(default_factory=dict)
    columns_added: list[str] = field(default_factory=list)
    columns_renamed: dict[str, str] = field(default_factory=dict)
    decisions: list[str] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)

    def to_yaml(self) -> str:
        """Serialise to YAML for saving alongside the cleaned data."""
        raise NotImplementedError

    def save(self, path: Path) -> None:
        """Write the log to <cleaned_output>.cleaning_log.yaml."""
        raise NotImplementedError


def stable_uuid() -> str:
    """Generate a stable UUID4 string for an internal row id."""
    return str(uuid.uuid4())


def fix_invalid_geometries(gdf: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, int]:
    """Make all geometries valid. Returns (gdf, n_dropped)."""
    raise NotImplementedError


def clip_to_aoi(
    gdf: gpd.GeoDataFrame,
    aoi: gpd.GeoDataFrame,
    buffer_m: float = 0,
) -> gpd.GeoDataFrame:
    """Clip a GeoDataFrame to the AOI (optionally buffered).

    Both inputs must be in EPSG:31370.
    """
    raise NotImplementedError
