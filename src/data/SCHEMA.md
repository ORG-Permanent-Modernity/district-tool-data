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
| `use_hint`          | `str`       | —    | Heuristic use: `residential`, `commercial`, `mixed`, `industrial`, `unknown`. Defaults to `unknown` in v0. |
| `attrs`             | `dict`      | —    | JSON blob of source-specific attributes not promoted to columns.           |

### Field notes

**`height_source` priority order (during cleaning):**
1. If building intersects GRB 3D LOD1/LOD2 coverage → use that height, mark `3dgrb`.
2. Else, zonal statistics (median) of DSM minus DTM within the footprint → mark `dhm_derived`.
3. Else, fallback to OSM height tag if available → mark `osm`.
4. Else `null` / `null`.

**`estimated_storeys` is a heuristic.** A 3m per storey assumption overestimates for Belgian historical buildings (often 3.5–4m) and underestimates for modern offices (often 2.8–3.2m). Treat as a rough indicator for population synthesis; not a substitute for floor-by-floor data.

**`roof_type`** comes from GRB 3D LOD2 classification where available. Approximate for irregular roofs; reliable for simple gabled and flat roofs.

**`use_hint`** is not populated in v0 from GRB alone. Future versions will join:
- CRAB/Adressenregister address density → residential signal
- OSM building tags → fallback
- Municipal building-use datasets where available

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
