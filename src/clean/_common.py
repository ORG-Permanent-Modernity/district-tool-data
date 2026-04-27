"""Shared utilities for cleaning scripts.

Every cleaning script in src/clean/<dataset>.py uses helpers from here for:
- The CleaningLog data structure (records what cleaning did)
- RasterCleaningLog for raster datasets
- Common geometry validity fixes
- AOI clipping
- Stable UUID generation
- Writing cleaned output + log alongside
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import shapely
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

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialisation."""
        # Convert numpy integers to Python integers for YAML compatibility
        rows_dropped = {k: int(v) for k, v in self.rows_dropped.items()}
        return {
            "dataset": self.dataset,
            "raw_input_path": self.raw_input_path,
            "cleaned_output_path": self.cleaned_output_path,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "rows_in": int(self.rows_in),
            "rows_out": int(self.rows_out),
            "rows_dropped": rows_dropped,
            "columns_added": self.columns_added,
            "columns_renamed": self.columns_renamed,
            "decisions": self.decisions,
            "anomalies": self.anomalies,
        }

    def to_yaml(self) -> str:
        """Serialise to YAML for saving alongside the cleaned data."""
        return yaml.safe_dump(self.to_dict(), default_flow_style=False, sort_keys=False)

    def save(self, path: Path | None = None) -> None:
        """Write the log to <cleaned_output>.cleaning_log.yaml."""
        if path is None:
            path = Path(self.cleaned_output_path + ".cleaning_log.yaml")
        with path.open("w") as f:
            f.write(self.to_yaml())


@dataclass
class RasterCleaningLog:
    """Records what a raster cleaning script did."""

    dataset: str
    raw_input_path: str
    cleaned_output_path: str
    started_at: datetime
    finished_at: datetime | None = None

    crs: str = ""
    resolution_m: float = 0.0
    shape: tuple[int, int] = (0, 0)
    bounds: tuple[float, float, float, float] = (0, 0, 0, 0)
    dtype: str = ""
    nodata: float | None = None
    tiles_mosaicked: int = 0
    decisions: list[str] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialisation."""
        return {
            "dataset": self.dataset,
            "raw_input_path": self.raw_input_path,
            "cleaned_output_path": self.cleaned_output_path,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "crs": self.crs,
            "resolution_m": self.resolution_m,
            "shape": list(self.shape),
            "bounds": list(self.bounds),
            "dtype": self.dtype,
            "nodata": self.nodata,
            "tiles_mosaicked": self.tiles_mosaicked,
            "decisions": self.decisions,
            "anomalies": self.anomalies,
        }

    def to_yaml(self) -> str:
        """Serialise to YAML for saving alongside the cleaned data."""
        return yaml.safe_dump(self.to_dict(), default_flow_style=False, sort_keys=False)

    def save(self, path: Path | None = None) -> None:
        """Write the log to <cleaned_output>.cleaning_log.yaml."""
        if path is None:
            path = Path(self.cleaned_output_path + ".cleaning_log.yaml")
        with path.open("w") as f:
            f.write(self.to_yaml())


def stable_uuid() -> str:
    """Generate a stable UUID4 string for an internal row id."""
    return str(uuid.uuid4())


def fix_invalid_geometries(gdf: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, int]:
    """Make all geometries valid. Returns (gdf, count_fixed).

    Uses shapely.make_valid to repair invalid geometries.
    Drops any that cannot be repaired or become empty.
    """
    gdf = gdf.copy()
    invalid_mask = ~gdf.geometry.is_valid
    n_invalid = invalid_mask.sum()

    if n_invalid > 0:
        gdf.loc[invalid_mask, "geometry"] = gdf.loc[invalid_mask, "geometry"].apply(
            shapely.make_valid
        )

    # Drop any that are now empty
    empty_mask = gdf.geometry.is_empty
    n_dropped = empty_mask.sum()
    if n_dropped > 0:
        gdf = gdf[~empty_mask]

    return gdf, n_dropped


def clip_to_aoi(
    gdf: gpd.GeoDataFrame,
    aoi: gpd.GeoDataFrame,
    buffer_m: float = 0,
) -> gpd.GeoDataFrame:
    """Clip a GeoDataFrame to the AOI (optionally buffered).

    Both inputs must be in EPSG:31370.
    """
    clip_geom = aoi.union_all()
    if buffer_m > 0:
        clip_geom = clip_geom.buffer(buffer_m)
    return gdf.clip(clip_geom)
