# Data Schema — District Analysis Tool

This document describes the canonical schema that the data layer (`DataLoader`) exposes to the rest of the application. It complements the docstrings in `loader.py` with domain-level context: what each column *means*, where values come from, units, null handling, and known gotchas.

**Scope:** v0 (Antwerp / Zurenborg). Schema extends as new datasets are ingested.

**Storage format (internal):** GeoPackage (`.gpkg`) for vectors, GeoTIFF for rasters, both in EPSG:31370 (Belgian Lambert 72). Future migration to Postgres will not change this schema — only the underlying storage.

**Conventions:**
- Nullable columns are marked with `?` in type annotations.
- `m` = metres. All linear measurements are metric.
- `m²` = square metres.
- All identifiers are strings (UUIDs) unless otherwise stated.

---

## Buildings

**Method:** `loader.buildings() -> gpd.GeoDataFrame`

**Source:** GRB Gebouw aan de grond (Grootschalig Referentiebestand), via catalogue id `grb_gebouwen`. Heights derived from DHM-II DSM minus DTM, or (where available) from GRB 3D (LOD1/LOD2).

**Coverage:** Full neighbourhood AOI. Typically 500–5000 rows per neighbourhood.

**Known gaps:**
- GRB does not provide building use or function. `use_hint` is heuristic — see below.
- ~3% of buildings in coastal or industrial areas have null `height_m` because of DHM coverage gaps.
- Very recently completed buildings (<6 months) may be missing entirely from GRB.

### Columns

| Column              | Type        | Unit | Description                                                                |
|---------------------|-------------|------|----------------------------------------------------------------------------|
| `id`                | `str`       | —    | Stable internal UUID. Use this for all joins and references.               |
| `source_id`         | `str`       | —    | GRB OIDN (original source id). For debugging and trace-back only.          |
| `geometry`          | `Polygon`   | —    | Footprint polygon in EPSG:31370.                                           |
| `height_m`          | `float?`    | m    | Building height above ground level. Nullable.                              |
| `height_source`     | `str?`      | —    | How the height was derived: `dhm_derived`, `3dgrb`, `osm`, or `null`.      |
| `roof_type`         | `str?`      | —    | `flat`, `pitched`, `mixed`, or `null` (where not classifiable).            |
| `area_m2`           | `float`     | m²   | Footprint area. Computed at cleaning time; always non-null.                |
| `estimated_storeys` | `int?`      | —    | Floor count estimated as `height_m / 3.0`, rounded. Null if height is null.|
| `use_hint`          | `str`       | —    | Heuristic use: `residential`, `commercial`, `mixed`, `industrial`, `accessory`, `unknown`. See below. |
| `attrs`             | `dict`      | —    | JSON blob of source-specific attributes not promoted to columns.           |

### Field notes

**`height_source` priority order (during cleaning):**
1. If building intersects GRB 3D LOD1/LOD2 coverage → use that height, mark `3dgrb`.
2. Else, zonal statistics (median) of DSM minus DTM within the footprint → mark `dhm_derived`.
3. Else, fallback to OSM height tag if available → mark `osm`.
4. Else `null` / `null`.

**`estimated_storeys` is a heuristic.** A 3m per storey assumption overestimates for Belgian historical buildings (often 3.5–4m) and underestimates for modern offices (often 2.8–3.2m). Treat as a rough indicator for population synthesis; not a substitute for floor-by-floor data.

**`roof_type`** comes from GRB 3D LOD2 classification where available. Approximate for irregular roofs; reliable for simple gabled and flat roofs.

**`use_hint`** is classified using address join and building size heuristics:
- `residential`: Building has address(es) and area ≥ 50m²
- `accessory`: No address and area < 50m² (sheds, garages, outbuildings)
- `industrial`: No address and area > 200m² (warehouses, utility buildings)
- `unknown`: No address and 50-200m² (ambiguous cases)
- `commercial`, `mixed`: Not yet populated (future: OSM tags, municipal datasets)

This is a heuristic classification with known limitations. Buildings without addresses in the 50-200m² range could be attached annexes, workshops, or commercial buildings. For defensible land-use analysis, supplement with OSM building tags or municipal zoning data.

### Typical queries

```python
# All residential buildings taller than 4 storeys
tall_res = buildings[
    (buildings.use_hint == "residential")
    & (buildings.estimated_storeys >= 4)
]

# Footprints only, drop nulls for a specific analysis
usable = buildings.dropna(subset=["height_m"])
```

---

## Roads

**Method:** `loader.roads() -> gpd.GeoDataFrame`

**Source:** Wegenregister (Flemish routable road register), via catalogue id `wegenregister`.

**Coverage:** All road segments intersecting the AOI. Includes segments extending beyond the AOI boundary — these can be clipped by the caller if needed.

**Known gaps:**
- Cycle infrastructure is presence/absence only — no quality or segregation detail.
- No turn-restriction information.
- Private service roads (e.g. inside parcels) are not included.

### Columns

| Column       | Type          | Unit | Description                                                       |
|--------------|---------------|------|-------------------------------------------------------------------|
| `id`         | `str`         | —    | Stable internal UUID.                                             |
| `source_id`  | `str`         | —    | Wegenregister `WS_OIDN`.                                          |
| `geometry`   | `LineString`  | —    | Road axis in EPSG:31370.                                          |
| `road_class` | `str`         | —    | `highway`, `arterial`, `local`, `cycleway`, `pedestrian`, `service`. |
| `speed_kmh`  | `int?`        | km/h | Posted speed limit. Nullable.                                     |
| `direction`  | `str`         | —    | `both`, `forward`, `backward`.                                    |
| `name`       | `str?`        | —    | Street name in Dutch. Nullable.                                   |
| `length_m`   | `float`       | m    | Segment length.                                                   |

### Field notes

**`road_class`** is normalised from Wegenregister's MORFCODE. Rough mapping:
- MORFCODE 101 (highway) → `highway`
- MORFCODE 102, 104 (regional/arterial) → `arterial`
- MORFCODE 105–108 (local) → `local`
- MORFCODE 113 (pedestrian) → `pedestrian`
- MORFCODE 114 (cycleway) → `cycleway`
- Others → `service`

This is a lossy normalisation — consumers needing finer detail should use the `source_id` to re-fetch from Wegenregister.

---

## Trees

**Method:** `loader.trees() -> gpd.GeoDataFrame`

**Source:** Stad Antwerpen tree inventory (catalogue id `antwerp_trees`) for Antwerp neighbourhoods.

**Coverage:** Municipally-managed trees only. **Private-garden trees, park stands, and street trees not yet inventoried are excluded.** For complete canopy analysis, use LiDAR-derived nDSM instead of or alongside this.

### Columns

| Column                     | Type      | Unit | Description                                         |
|----------------------------|-----------|------|-----------------------------------------------------|
| `id`                       | `str`     | —    | Stable internal UUID.                               |
| `source_id`                | `str`     | —    | Municipal tree id.                                  |
| `geometry`                 | `Point`   | —    | Tree location in EPSG:31370.                        |
| `species`                  | `str?`    | —    | Latin name. Nullable.                               |
| `common_name`              | `str?`    | —    | Dutch common name. Nullable.                        |
| `planted_year`             | `int?`    | —    | Year planted. Nullable.                             |
| `diameter_class`           | `str?`    | —    | Source category (e.g. `20-40cm`). Nullable.         |
| `estimated_crown_radius_m` | `float`   | m    | Heuristic crown radius from diameter class.         |

### Field notes

**`estimated_crown_radius_m`** is derived from `diameter_class` using a lookup table (crown-to-stem diameter ratio ~10:1 for mature urban trees). Unreliable for young or recently pruned trees. If trees are absent or the diameter class is null, defaults to 2.5m.

---

## Terrain (DSM, DTM, nDSM)

**Methods:**
- `loader.terrain_dsm() -> (array, transform, epsg)`
- `loader.terrain_dtm() -> (array, transform, epsg)`
- `loader.terrain_ndsm() -> (array, transform, epsg)`

**Source:** DHM-II (Digitaal Hoogtemodel Vlaanderen II), via catalogue ids `dhm_vlaanderen_dsm` and `dhm_vlaanderen_dtm`.

**Coverage:** Full neighbourhood, clipped to the AOI with a small buffer.

**Resolution:** 1m preferred, 5m fallback where 1m is unavailable.

### Return shape

All three methods return a 3-tuple: `(array, transform, crs_epsg)`.

- **`array`**: 2D `numpy.ndarray`, dtype `float32`, shape `(H, W)`. Values are elevation in metres TAW (Tweede Algemene Waterpassing, the Belgian vertical datum).
- **`transform`**: `rasterio.Affine` transform mapping array indices to EPSG:31370 coordinates.
- **`crs_epsg`**: `31370` (always).

### Semantics

- **DSM**: top-of-surface elevation — includes buildings, trees, other above-ground features.
- **DTM**: bare-earth elevation — buildings and vegetation removed.
- **nDSM**: `DSM - DTM`, clipped to ≥ 0. Represents above-ground height at each pixel. Used for canopy-height and building-height analysis.

### Field notes

**TAW vs EGM**: TAW is ~2.3m below EGM2008 at Brussels. This matters only if integrating with non-Belgian elevation data. Within Flanders, all sources use TAW.

**nDSM negatives**: raw `DSM - DTM` can produce slightly negative values in water bodies or at tile seams. The loader clips these to zero on return.

**Tile seams**: DHM-II is delivered as 1km×1km tiles. Cleaning merges tiles into neighbourhood-level rasters; edge effects are minor but possible.

---

## AOI

**Method:** `loader.aoi() -> gpd.GeoDataFrame`

Single-feature GeoDataFrame with one Polygon geometry in EPSG:31370 — the boundary of the neighbourhood. Used by modules that need to clip results or generate analysis grids scoped to the neighbourhood.

---

## Metadata

**Property:** `loader.meta -> dict`
**Method:** `loader.dataset_info(key) -> dict`

Every dataset has a metadata entry in `meta.yaml`. Consumers can access it to:
- Check which version of source data was used (for reproducibility)
- Display provenance in API responses
- Audit when data was last reviewed

Structure per dataset:

```yaml
buildings:
  source: grb_gebouwen          # catalogue id
  source_version: "2026-04-15"  # provider-supplied version
  ingested_at: "2026-04-18"     # when fetched from source
  cleaned_at: "2026-04-19"      # when cleaning pipeline ran
  reviewed_at: "2026-04-20"     # when promoted cleaned → reviewed
  reviewer: "John"
  notes: "Spot-checked against cadastre; heights look sensible."
```

---

## Statistical Sectors

**Method:** `loader.sectors() -> gpd.GeoDataFrame`

**Source:** Statbel statistical sectors (catalogue id `statbel_sectors`) with population data joined from Statbel population-by-sector.

**Coverage:** All sectors intersecting the AOI. Sectors are kept as whole polygons (not clipped) since they are statistical units.

**Known gaps:**
- Population data is an annual snapshot — no intra-year updates
- Sector boundaries change periodically (REDEGEO reform in 2025)
- Area and population for sectors extending beyond AOI reflects full sector, not clipped portion

### Columns

| Column               | Type      | Unit   | Description                                           |
|----------------------|-----------|--------|-------------------------------------------------------|
| `id`                 | `str`     | —      | Stable internal UUID.                                 |
| `source_id`          | `str`     | —      | Sector code (CD_SECTOR).                              |
| `geometry`           | `Polygon` | —      | Sector boundary in EPSG:31370.                        |
| `name_nl`            | `str?`    | —      | Dutch name. Nullable.                                 |
| `name_fr`            | `str?`    | —      | French name. Nullable.                                |
| `municipality_nis`   | `str?`    | —      | Municipality NIS code.                                |
| `area_m2`            | `float`   | m²     | Official sector area.                                 |
| `population`         | `int?`    | —      | Total population (from Statbel). Nullable.            |
| `pop_density_per_km2`| `float?`  | /km²   | Population density. Nullable.                         |

### Field notes

**`population`** is the total headcount from the Statbel annual snapshot. Does not include age/gender breakdown (available in separate Statbel tables).

**`pop_density_per_km2`** is computed as `population / area_m2 * 1,000,000`. Useful for comparing sectors of different sizes.

---

## Canopy (LiDAR-derived)

**Methods:**
- `loader.canopy_chm() -> (array, transform, epsg)` — raster
- `loader.canopy_polygons() -> gpd.GeoDataFrame` — vector

**Source:** Derived from DHM-II nDSM by masking building footprints. Buildings from GRB.

**Coverage:** Full neighbourhood AOI. Captures ALL vegetation including private gardens, not just municipal trees.

**Known limitations:**
- **Temporal mismatch**: DHM-II was captured 2013-2015. Trees planted since then are missing; trees removed since then appear as phantom canopy.
- **Tall hedges** (>2.5m) are included as canopy — they provide similar shading.
- **Green roofs** are excluded (masked with building footprints).
- At 1m resolution, individual tree trunks are not resolved.

### Canopy Height Model (Raster)

**Method:** `loader.canopy_chm() -> (array, transform, epsg)`

Returns a 3-tuple: `(array, transform, crs_epsg)`.

- **`array`**: 2D `numpy.ndarray`, dtype `float32`, shape `(H, W)`. Above-ground vegetation height in metres. Buildings and nodata areas are `-9999`.
- **`transform`**: `rasterio.Affine` transform mapping array indices to EPSG:31370 coordinates.
- **`crs_epsg`**: `31370` (always).

### Canopy Polygons (Vector)

**Method:** `loader.canopy_polygons() -> gpd.GeoDataFrame`

| Column          | Type      | Unit | Description                                    |
|-----------------|-----------|------|------------------------------------------------|
| `id`            | `str`     | —    | Stable internal UUID.                          |
| `geometry`      | `Polygon` | —    | Canopy footprint in EPSG:31370.                |
| `area_m2`       | `float`   | m²   | Polygon area.                                  |
| `mean_height_m` | `float?`  | m    | Mean vegetation height within polygon.         |
| `max_height_m`  | `float?`  | m    | Maximum vegetation height within polygon.      |

### Derivation parameters (for reproducibility)

- **Height threshold**: 2.5m (vegetation must exceed this to be counted)
- **Building buffer**: 1.0m (buildings buffered before masking to avoid edge effects)
- **Minimum polygon area**: 4.0 m² (smaller fragments filtered as noise)
- **Morphological cleanup**: Opening (2px kernel) + closing (3px kernel)

### Typical queries

```python
# Total canopy coverage in neighbourhood
total_ha = canopy_polygons["area_m2"].sum() / 10000

# Large canopy patches (mature stands)
large = canopy_polygons[canopy_polygons["area_m2"] > 100]

# Tall trees
tall = canopy_polygons[canopy_polygons["max_height_m"] > 20]
```

---

## Vegetation (NDVI-derived)

**Method:** `loader.vegetation() -> gpd.GeoDataFrame`

**Source:** NDVI thresholding on 2021 summer CIR orthophoto (40cm resolution).

**Coverage:** All green vegetation in the neighbourhood, including trees, shrubs, hedges, and gardens. Uses 2021 imagery to capture recent plantings that would be missing from the 2013-2015 LiDAR.

**Pipeline:**
1. Compute NDVI from CIR orthophoto bands (NIR, Red)
2. Threshold: NDVI >= 0.05 (any green vegetation)
3. Morphological cleanup: opening (1px) + closing (2px)
4. Vectorize to polygons
5. Filter: minimum area 2 m²
6. Compute height stats from nDSM (for reference, may be outdated)

**Trade-offs vs LiDAR-only (`canopy_polygons`):**
- **More current**: uses 2021 imagery vs 2013-2015 LiDAR
- **Better coverage**: captures recent plantings, small trees
- **Includes more vegetation types**: not just tall trees
- **No height filtering**: avoids DHM-II temporal mismatch

**Methods evaluated (for reference):**
- nDSM-only: 5.82 ha — misses trees planted after 2015
- DeepForest ML: 1.07 ha — too restrictive, rectangular artifacts
- NDVI + height fusion: temporal mismatch issues
- **NDVI-only (chosen)**: 12.21 ha — best coverage with 2021 imagery

**Known limitations:**
- Height data (mean_height_m, max_height_m) is from DHM-II (2013-2015) — may be inaccurate for recent plantings
- DHM-III expected 2028 — will enable accurate height filtering
- Includes shrubs and hedges, not just trees

### Columns

| Column          | Type      | Unit | Description                                    |
|-----------------|-----------|------|------------------------------------------------|
| `id`            | `str`     | —    | Stable internal UUID.                          |
| `geometry`      | `Polygon` | —    | Vegetation footprint in EPSG:31370.            |
| `area_m2`       | `float`   | m²   | Polygon area.                                  |
| `mean_height_m` | `float?`  | m    | Mean height (from nDSM, may be outdated).      |
| `max_height_m`  | `float?`  | m    | Max height (from nDSM, may be outdated).       |

### Derivation parameters

- **NDVI threshold**: 0.05
- **Height threshold**: none (temporal mismatch with DHM-II)
- **Morphological cleanup**: opening 1px, closing 2px
- **Minimum polygon area**: 2.0 m²

### Typical queries

```python
# Total vegetation coverage
total_ha = vegetation["area_m2"].sum() / 10000

# Compare with tree inventory
trees_buffered = trees.buffer(trees["estimated_crown_radius_m"]).area.sum() / 10000
coverage_ratio = total_ha / trees_buffered  # > 1 indicates vegetation beyond inventory
```

---

## Addresses

**Method:** `loader.addresses() -> gpd.GeoDataFrame`

**Source:** Adressenregister (Flemish address register) via WFS.

**Coverage:** All addresses in the neighbourhood. Points clipped strictly to AOI.

**Pipeline:**
1. Fetch from Adressenregister WFS with bbox filter
2. Clip to AOI
3. Extract address fields
4. Optionally join to nearest building

### Columns

| Column          | Type     | Unit | Description                                    |
|-----------------|----------|------|------------------------------------------------|
| `id`            | `str`    | —    | Stable internal UUID.                          |
| `source_id`     | `str`    | —    | Adressenregister object ID.                    |
| `geometry`      | `Point`  | —    | Address location in EPSG:31370.                |
| `full_address`  | `str`    | —    | Complete address string.                       |
| `street_name`   | `str`    | —    | Street name.                                   |
| `house_number`  | `str?`   | —    | House number (may be null).                    |
| `municipality`  | `str`    | —    | Municipality name.                             |
| `building_id`   | `str?`   | —    | Nearest building ID (if joined).               |

### Typical queries

```python
# Addresses per street
addresses.groupby("street_name").size().sort_values(ascending=False)

# Join addresses to buildings
buildings_with_addresses = buildings.merge(
    addresses.groupby("building_id").size().reset_index(name="n_addresses"),
    left_on="id", right_on="building_id", how="left"
)
```

---

## BWK (Biological Valuation Map)

**Method:** `loader.bwk() -> gpd.GeoDataFrame`

**Source:** BWK (Biologische Waarderingskaart) from INBO via WFS.

**Coverage:** Wall-to-wall habitat classification for Flanders. Clipped to AOI.

**Note:** Update cycles are multi-year; urban areas may be 5-10 years out of date.
For current vegetation, supplement with `vegetation()` from NDVI or `canopy_polygons()` from LiDAR.

### Columns

| Column           | Type      | Unit | Description                                    |
|------------------|-----------|------|------------------------------------------------|
| `id`             | `str`     | —    | Stable internal UUID.                          |
| `source_id`      | `str`     | —    | BWK OIDN.                                      |
| `geometry`       | `Polygon` | —    | Biotope polygon in EPSG:31370.                 |
| `primary_biotope`| `str?`    | —    | Primary biotope code (e.g., 'ha', 'sf').       |
| `classification` | `str?`    | —    | TAG classification.                            |
| `valuation`      | `str`     | —    | Ecological value: see below.                  |
| `area_m2`        | `float`   | m²   | Polygon area.                                  |

### Valuation values

- `very_valuable` — zeer waardevol
- `valuable` — biologisch waardevol
- `less_valuable` — minder waardevol
- `mixed` — complex
- `unknown` — no valuation

### Biotope codes (common)

- `ha` — lawn (gazon)
- `hp` — pasture
- `sf` — shrub
- `kb` — artificial/urban
- `kw` — industrial
- `weg` — road
- `spoor` — railway

### Typical queries

```python
# Valuable habitat area
valuable = bwk[bwk["valuation"].isin(["very_valuable", "valuable"])]
valuable_ha = valuable["area_m2"].sum() / 10000

# Biotope distribution
bwk["primary_biotope"].value_counts()
```

---

## Invariants

Properties the loader guarantees (and modules can rely on):

- **CRS**: every vector/raster result is in EPSG:31370.
- **Non-empty geometries**: no null or empty geometries in vector returns.
- **Stable IDs**: `id` columns are UUIDs, stable across reads. Safe to use as join keys.
- **Units**: all linear measurements in metres, all areas in square metres, all angles in degrees unless noted.
- **Schema stability**: within a major version of the loader, columns may be added but not renamed or removed.
- **Review discipline**: data returned by the loader has passed human review (promoted from `cleaned/` to `reviewed/`). Raw and cleaned-but-unreviewed data are not accessible through the loader.

---

## What the loader does NOT do

Explicitly out of scope, so consumers don't hunt for it:

- **Filtering by bbox or attributes**: do it on the returned DataFrame. For v0 neighbourhoods are small enough that full loads are fine.
- **Writes**: the loader is read-only.
- **Transforming to web CRS**: happens at the API boundary, not here.
- **Caching**: simple v0. If profiling shows it matters, add `functools.lru_cache` or similar inside method bodies.
- **Providing raw or cleaned data**: loader only exposes `reviewed/`. If you need to debug upstream, open the files in QGIS directly.

---

## Extending the schema

When adding a new dataset:

1. Add an ingest script to `src/ingest/<dataset>.py`.
2. Add a cleaning script to `src/clean/<dataset>.py`.
3. Promote reviewed data to `reviewed/<dataset>.gpkg` (or `.tif`).
4. Add an entry to `meta.yaml` for the neighbourhood.
5. Add a method to `DataLoader` with full docstring.
6. Add a section to this document.
7. Update `API_SHAPE.md` if exposing the dataset via the API.

The order matters: get the loader method and schema documented *before* any module consumes the new data. Schema documented badly now is worse than schema documented late.
