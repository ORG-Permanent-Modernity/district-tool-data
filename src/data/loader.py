"""Data loader for the district analysis tool.

This is the single interface through which the application reads reference
data. All file paths, formats, and storage details live here. Downstream
code asks for domain concepts ('buildings', 'terrain'), not files.

Returns data in source CRS (EPSG:31370 for Belgian datasets).
Reprojection for web display happens at the API boundary, not here.

IMPORTANT: Modules, API endpoints, notebooks, and analysis scripts MUST
go through this class for data access. Do not read files directly from
other parts of the codebase. The loader is what makes a future migration
(to Postgres, to a cloud data service, etc.) a one-file change rather
than a rewrite.

Usage:
    >>> loader = DataLoader(city="antwerp", neighbourhood="zurenborg")
    >>> buildings = loader.buildings()
    >>> dsm, transform, epsg = loader.terrain_dsm()
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
import yaml
from rasterio.transform import Affine


# Read from environment / config in real implementation
DATA_ROOT = Path("/path/to/district-tool-data")


class DataLoader:
    """The single interface through which the application reads reference data.

    One loader instance corresponds to one (city, neighbourhood) pair.
    Methods are named by domain concept, not by source dataset.

    All vector methods return GeoDataFrames in EPSG:31370.
    All raster methods return (array, transform, epsg) tuples in EPSG:31370.
    """

    def __init__(self, city: str, neighbourhood: str):
        """Construct a loader for one (city, neighbourhood).

        Args:
            city: Lowercase city identifier matching the folder name
                  (e.g. 'antwerp').
            neighbourhood: Lowercase neighbourhood identifier matching the
                  folder name (e.g. 'zurenborg').

        Raises:
            FileNotFoundError: if the neighbourhood folder does not exist.
        """
        self.city = city
        self.neighbourhood = neighbourhood
        self.base = DATA_ROOT / city / neighbourhood
        self._reviewed = self.base / "reviewed"
        self._meta: dict | None = None

    # ----------------- metadata and discovery -----------------

    @property
    def meta(self) -> dict:
        """Metadata about which datasets are available and their versions.

        Loaded lazily on first access. See meta.yaml in the neighbourhood
        folder for the canonical format.

        Returns:
            dict keyed by dataset id. Each value has keys:
                source: str           Catalogue id of the source dataset
                source_version: str   The provider's version
                ingested_at: str      ISO date of the ingest
                reviewed_at: str      ISO date of the review/promotion
                reviewer: str         Who promoted cleaned -> reviewed
                notes: str            Optional review notes
        """
        ...

    def aoi(self) -> gpd.GeoDataFrame:
        """The neighbourhood boundary polygon.

        Returns:
            Single-feature GeoDataFrame with one Polygon in EPSG:31370.
        """
        ...

    def available(self) -> list[str]:
        """List of dataset keys available for this neighbourhood.

        Returns:
            List of dataset ids present in meta.yaml, e.g.
            ['buildings', 'roads', 'trees', 'terrain_dsm', 'terrain_dtm'].
        """
        ...

    def dataset_info(self, key: str) -> dict:
        """Provenance info for one dataset.

        Args:
            key: Dataset id, e.g. 'buildings'.

        Returns:
            The metadata dict for that dataset (source, version, dates).

        Raises:
            KeyError: if the dataset is not available for this neighbourhood.
        """
        ...

    # ----------------- vector datasets -----------------

    def buildings(self) -> gpd.GeoDataFrame:
        """Building footprints with heights and attributes.

        See SCHEMA.md for full column documentation.

        Columns (EPSG:31370):
            id                   : str      Stable internal UUID
            source_id            : str      Original source id (e.g. GRB OIDN)
            geometry             : Polygon  Footprint
            height_m             : float?   Building height in metres, nullable
            height_source        : str?     'dhm_derived' | '3dgrb' | 'osm' | null
            roof_type            : str?     'flat' | 'pitched' | 'mixed' | null
            area_m2              : float    Footprint area
            estimated_storeys    : int?     Derived from height_m / 3.0
            use_hint             : str      'residential' | 'commercial' |
                                            'mixed' | 'industrial' | 'accessory' | 'unknown'
            attrs                : dict     Source-specific extra attributes

        Returns:
            GeoDataFrame, EPSG:31370. Typically 500-5000 rows at neighbourhood
            scale.
        """
        ...

    def roads(self) -> gpd.GeoDataFrame:
        """Road network from Wegenregister.

        Columns (EPSG:31370):
            id              : str          Stable internal UUID
            source_id       : str          Wegenregister WS_OIDN
            geometry        : LineString   Road axis
            road_class      : str          'highway' | 'arterial' | 'local' |
                                           'cycleway' | 'pedestrian' | 'service'
            speed_kmh       : int?         Posted speed limit, nullable
            direction       : str          'both' | 'forward' | 'backward'
            name            : str?         Street name, nullable
            length_m        : float        Segment length

        Returns:
            GeoDataFrame, EPSG:31370.
        """
        ...

    def trees(self) -> gpd.GeoDataFrame:
        """Municipal tree inventory.

        Coverage: municipally-managed trees only. Private-garden trees and
        some park stands are NOT included. For canopy-fraction analyses,
        supplement with LiDAR-derived nDSM.

        Columns (EPSG:31370):
            id                         : str     Stable internal UUID
            source_id                  : str     Municipal tree id
            geometry                   : Point
            species                    : str?    Latin name, nullable
            common_name                : str?    Dutch name, nullable
            planted_year               : int?    Nullable
            diameter_class             : str?    Source category, nullable
            estimated_crown_radius_m   : float   Heuristic from diameter class

        Returns:
            GeoDataFrame, EPSG:31370.
        """
        ...

    # ----------------- raster datasets -----------------

    def terrain_dsm(self) -> tuple[np.ndarray, Affine, int]:
        """Digital Surface Model (top-of-canopy / roof).

        1m resolution where available, falling back to 5m otherwise.
        Includes buildings, trees, and other above-ground features.

        Returns:
            Tuple of (array, transform, crs_epsg).
            - array: 2D numpy float32, shape (H, W). Elevation in metres TAW.
            - transform: rasterio Affine transform.
            - crs_epsg: 31370 (Belgian Lambert 72).
        """
        ...

    def terrain_dtm(self) -> tuple[np.ndarray, Affine, int]:
        """Digital Terrain Model (bare earth, no buildings or vegetation).

        1m resolution where available, falling back to 5m otherwise.

        Returns:
            Tuple of (array, transform, crs_epsg). Same shape/CRS as DSM.
        """
        ...

    def terrain_ndsm(self) -> tuple[np.ndarray, Affine, int]:
        """Normalised DSM (DSM - DTM): above-ground height at each pixel.

        Computed from DSM and DTM on load if not pre-computed.
        Negative values are clipped to zero.

        Returns:
            Tuple of (array, transform, crs_epsg).
        """
        ...

    def sectors(self) -> gpd.GeoDataFrame:
        """Statistical sectors with population data.

        Statbel statistical sectors are the finest-grained demographic units
        in Belgium. Population data from Statbel is joined to sector polygons.

        Note: Sectors are kept as whole polygons (not clipped to AOI) since
        they are statistical units. Some sectors may extend beyond the
        neighbourhood boundary.

        Columns (EPSG:31370):
            id                   : str     Stable internal UUID
            source_id            : str     Sector code (CD_SECTOR)
            geometry             : Polygon Sector boundary
            name_nl              : str?    Dutch name
            name_fr              : str?    French name
            municipality_nis     : str?    Municipality NIS code
            area_m2              : float   Official sector area
            population           : int?    Total population (from Statbel)
            pop_density_per_km2  : float?  Population per km²

        Returns:
            GeoDataFrame, EPSG:31370.
        """
        ...

    def canopy_chm(self) -> tuple[np.ndarray, Affine, int]:
        """Canopy Height Model (nDSM with buildings masked out).

        Derived from nDSM by masking building footprints. Shows above-ground
        vegetation heights. Buildings appear as nodata.

        Temporal note: Based on DHM-II (2013-2015). Trees planted since then
        are missing; trees removed since then appear as phantom canopy.

        Returns:
            Tuple of (array, transform, crs_epsg).
            - array: 2D numpy float32, shape (H, W). Height in metres.
                    Buildings and nodata areas are -9999.
            - transform: rasterio Affine transform.
            - crs_epsg: 31370.
        """
        ...

    def canopy_polygons(self) -> gpd.GeoDataFrame:
        """Canopy coverage polygons derived from LiDAR.

        Includes ALL above-ground vegetation > 2.5m height, not just
        municipal trees. Covers private gardens, parks, unmapped street
        trees, and tall hedges.

        For municipal tree inventory (point data with species info), use
        the trees() method instead.

        Columns (EPSG:31370):
            id             : str     Stable internal UUID
            geometry       : Polygon Canopy footprint
            area_m2        : float   Polygon area
            mean_height_m  : float?  Mean canopy height within polygon
            max_height_m   : float?  Max canopy height within polygon

        Returns:
            GeoDataFrame, EPSG:31370.
        """
        ...

    def vegetation(self) -> gpd.GeoDataFrame:
        """Vegetation polygons from NDVI (2021 summer orthophoto).

        All green vegetation detected from Color-Infrared imagery using NDVI
        thresholding. Uses 2021 orthophoto to avoid temporal mismatch with
        outdated DHM-II LiDAR (2013-2015).

        Coverage: All vegetation with NDVI >= 0.05, including:
            - Trees (all sizes, including recent plantings)
            - Shrubs and hedges
            - Gardens and green spaces
            - Excludes: grass lawns (low NDVI), bare soil, buildings

        Note: For height-filtered tree canopy only, use canopy_polygons()
        (based on nDSM). That dataset may miss trees planted after 2015.

        Columns (EPSG:31370):
            id             : str     Stable internal UUID
            geometry       : Polygon Vegetation footprint
            area_m2        : float   Polygon area
            mean_height_m  : float?  Mean height (from nDSM, may be outdated)
            max_height_m   : float?  Max height (from nDSM, may be outdated)

        Returns:
            GeoDataFrame, EPSG:31370.
        """
        ...

    def addresses(self) -> gpd.GeoDataFrame:
        """Address points from Adressenregister.

        Each address is a geocoded point with street name and municipality.
        Useful for address-based geocoding or joining external datasets.

        Columns (EPSG:31370):
            id             : str     Stable internal UUID
            source_id      : str     Adressenregister object ID
            geometry       : Point   Address location
            full_address   : str     Complete address string
            street_name    : str     Street name
            house_number   : str?    House number (may be null)
            municipality   : str     Municipality name
            building_id    : str?    Nearest building ID (if joined)

        Returns:
            GeoDataFrame, EPSG:31370.
        """
        ...

    def bwk(self) -> gpd.GeoDataFrame:
        """BWK (Biological Valuation Map) habitat polygons.

        The Biologische Waarderingskaart classifies all land into biotope
        categories with ecological valuation scores. Wall-to-wall coverage
        of Flanders.

        Note: Update cycles are multi-year; urban areas may be 5-10 years
        out of date. For current vegetation, supplement with vegetation()
        from NDVI or canopy_polygons() from LiDAR.

        Columns (EPSG:31370):
            id              : str     Stable internal UUID
            source_id       : str     BWK OIDN
            geometry        : Polygon Biotope polygon
            primary_biotope : str?    Primary biotope code (e.g., 'ha', 'sf')
            classification  : str?    TAG classification
            valuation       : str     Ecological value: 'very_valuable' |
                                      'valuable' | 'less_valuable' | 'mixed' |
                                      'unknown'
            area_m2         : float   Polygon area

        Returns:
            GeoDataFrame, EPSG:31370.
        """
        ...

    # ----------------- future extensions -----------------
    # When adding new datasets, follow the same pattern:
    #   - method named for the domain concept
    #   - returns GeoDataFrame (vector) or (array, transform, epsg) (raster)
    #   - EPSG:31370 always
    #   - full schema documented in docstring
    #   - update SCHEMA.md alongside
    #
    # Planned additions (not implemented yet):
    #   - land_use()       : Landgebruikskaart polygons
    #   - flood_hazard()   : Overstromingsgevoelige gebieden
    #   - noise_baseline() : Strategic noise map values at building facades
