# Antwerp First Ingest — Fetch Checklist

**City:** Antwerp
**Neighbourhood:** [TO DECIDE — Zurenborg suggested]
**Status:** Pre-ingest planning
**Last revised:** April 2026

This is the ordered fetch list for the first data round. Datasets are grouped by tier (priority) and listed within tier in dependency order — fetch top to bottom.

For each dataset:
- **Catalogue id** — the entry in `catalogue/*.yaml` to use
- **Endpoint** — which endpoint type from the catalogue (`wfs`, `download`, `api`)
- **Output** — where the cleaned-and-reviewed file lives in the data folder
- **Fetch parameters** — bbox/AOI, layer name (typeName), filters
- **Cleaning notes** — decisions to make explicit
- **Dependency** — which earlier dataset(s) must be in place

---

## Step 0 — Define the AOI

Before any data is fetched, the neighbourhood boundary polygon must exist.

- [ ] **AOI polygon for the chosen neighbourhood**
  - Source: trace in QGIS against OSM/aerial imagery, OR use a Statbel statistical sector polygon as a starting boundary
  - Output: `district-tool-data/antwerp/<neighbourhood>/aoi.gpkg`
  - CRS: EPSG:31370
  - Single polygon feature, attribute table can be empty
  - **This is the input every other ingest depends on.**

Suggested neighbourhoods for v0 (pick one):
- **Zurenborg** — historical residential, ~1500 buildings, well-defined boundaries (Dageraadplaats / Cogels-Osylei area)
- **Eilandje** — mixed contemporary, harbour-adjacent, ~600 buildings
- **Borgerhout intra-muros** — dense traditional grid, ~3000 buildings

---

## Tier 1 — Foundations (everything depends on these)

### [ ] 1. DHM-II DTM (Digital Terrain Model)

The bare-earth terrain raster. Fetched first because building heights depend on it.

- **Catalogue id:** `dhm_vlaanderen_dtm`
- **Endpoint:** `download` (tile-based) — go through the catalogue page, select tiles intersecting the AOI bbox + 200m buffer
- **Resolution:** 1m where available, fall back to 5m
- **Output (raw):** `raw/dhm_dtm_<YYYY-MM-DD>/<tile_id>.tif` (one file per source tile)
- **Output (cleaned):** `cleaned/terrain_dtm.tif` (single mosaicked raster, clipped to AOI + buffer)
- **Output (reviewed):** `reviewed/terrain_dtm.tif`
- **Cleaning steps:**
  - Mosaic source tiles into one raster
  - Clip to AOI + 200m buffer (the buffer matters — analyses near the AOI edge need data slightly beyond it)
  - Verify CRS is EPSG:31370
  - Verify nodata value is consistent
  - Write as Cloud-Optimized GeoTIFF (COG) for future-friendliness
- **Dependency:** AOI

### [ ] 2. DHM-II DSM (Digital Surface Model)

Top-of-canopy elevation. Same fetch pattern as DTM.

- **Catalogue id:** `dhm_vlaanderen_dsm`
- **Endpoint:** `download`
- **Resolution:** 1m where available
- **Output (raw):** `raw/dhm_dsm_<YYYY-MM-DD>/<tile_id>.tif`
- **Output (cleaned):** `cleaned/terrain_dsm.tif`
- **Output (reviewed):** `reviewed/terrain_dsm.tif`
- **Cleaning steps:** same as DTM (mosaic, clip, verify CRS, COG)
- **Dependency:** AOI

### [ ] 3. nDSM (computed)

Above-ground height = DSM − DTM, clipped to ≥ 0.

- **Source:** computed, not fetched
- **Output (cleaned):** `cleaned/terrain_ndsm.tif`
- **Output (reviewed):** `reviewed/terrain_ndsm.tif`
- **Cleaning steps:**
  - Subtract DTM from DSM
  - Clip negative values to zero (water bodies, tile seams)
  - Same CRS, extent, resolution as DSM/DTM
- **Dependency:** DSM and DTM both reviewed

### [ ] 4. GRB Buildings (footprints + heights)

- **Catalogue id:** `grb_gebouwen`
- **Endpoint:** `wfs` — `https://geo.api.vlaanderen.be/GRB/wfs`
- **Layer (typeName):** likely `GRB:Gbg` — confirm in service GetCapabilities
- **Filter:** bbox = AOI envelope + 100m buffer, in EPSG:31370
- **Output (raw):** `raw/grb_gebouwen_<YYYY-MM-DD>.gpkg`
- **Output (cleaned):** `cleaned/buildings.gpkg`
- **Output (reviewed):** `reviewed/buildings.gpkg`
- **Cleaning steps — make these decisions explicit and document in the script:**
  - **Drop buildings smaller than X m².** Suggested threshold: 10 m². Smaller features are usually garden sheds, bus shelters, etc. Document the threshold; revisit if results look wrong.
  - **Drop or fix invalid geometries** (`make_valid` from shapely).
  - **Clip strictly to AOI** (not buffered) for the reviewed output; the buffered fetch is just to avoid edge artefacts.
  - **Compute footprint area** as `area_m2`.
  - **Compute height** by zonal stats of nDSM within each footprint (median, ignoring nodata). Mark `height_source = 'dhm_derived'`.
  - **Add stable UUID** in `id` column. Keep GRB OIDN in `source_id`.
  - **Initialise `use_hint = 'unknown'`.** Population of this field is deferred.
  - **Compute `estimated_storeys` = round(height_m / 3.0).** Null where height_m is null.
- **Dependency:** AOI, terrain_ndsm
- **Notes:**
  - WFS may paginate — script must handle pagination (`startIndex`, `count` parameters in WFS 2.0).
  - WFS sometimes returns features intersecting the bbox edge; clip strictly during cleaning.
  - Some buildings may have null heights (DHM coverage gap or footprint smaller than DSM resolution). Keep them, but log the count.

### [ ] 5. GRB 3D buildings (LOD1/LOD2 heights and roof types) — optional, supplements step 4

Use this where coverage exists to upgrade the height_source from `dhm_derived` to `3dgrb`, and to populate `roof_type`.

- **Catalogue id:** `grb_3d`
- **Endpoint:** `download` (CityGML/CityJSON tiles)
- **Output (raw):** `raw/grb_3d_<YYYY-MM-DD>/<tile_id>.{json|gml}`
- **Cleaning steps:**
  - Parse CityGML/CityJSON, extract per-building height and roof type
  - Spatial-join to GRB footprints by source_id where possible, else by spatial nearest
  - Update `height_m`, `height_source = '3dgrb'`, `roof_type` for matched buildings
  - This UPDATES the cleaned `buildings.gpkg`, not a separate file
- **Dependency:** GRB Buildings (cleaned)
- **Notes:** if 3DGRB coverage doesn't include the chosen neighbourhood, skip — `dhm_derived` heights are fine.

---

## Tier 2 — Core layers for near-term modules

### [ ] 6. Wegenregister (routable road network)

- **Catalogue id:** `wegenregister`
- **Endpoint:** `wfs` — `https://geo.api.vlaanderen.be/Wegenregister/wfs`
- **Layer (typeName):** confirm in GetCapabilities — likely `Wegenregister:Wegsegment` or similar
- **Filter:** bbox = AOI envelope + 200m buffer
- **Output (raw):** `raw/wegenregister_<YYYY-MM-DD>.gpkg`
- **Output (cleaned):** `cleaned/roads.gpkg`
- **Output (reviewed):** `reviewed/roads.gpkg`
- **Cleaning steps:**
  - Normalise MORFCODE → `road_class` (see SCHEMA.md mapping)
  - Extract speed limit, name, direction
  - Compute `length_m`
  - Add stable UUID, keep WS_OIDN as `source_id`
  - Keep buffer in cleaned output (routing needs context beyond AOI)
- **Dependency:** AOI

### [ ] 7. Antwerp tree inventory

- **Catalogue id:** `antwerp_trees`
- **Endpoint:** `portal` / `metadata` — Antwerp ArcGIS Hub
- **Output (raw):** `raw/antwerp_trees_<YYYY-MM-DD>.gpkg`
- **Output (cleaned):** `cleaned/trees.gpkg`
- **Output (reviewed):** `reviewed/trees.gpkg`
- **Cleaning steps:**
  - Filter to AOI
  - Normalise species fields (some sources have Latin and Dutch in mixed columns)
  - Compute `estimated_crown_radius_m` from `diameter_class` lookup table — document the lookup in the cleaning script
  - Default crown radius to 2.5m where diameter_class is null
  - Add stable UUID, keep municipal id as `source_id`
- **Dependency:** AOI
- **Notes:** Antwerp's tree inventory may be served via ArcGIS FeatureServer rather than WFS. Adjust fetch logic accordingly.

### [ ] 8. Statbel statistical sectors

Polygons. Fetched separately from population.

- **Catalogue id:** `statbel_sectors`
- **Endpoint:** `portal` — download Shapefile / GeoPackage from Statbel
- **Filter:** filter to those intersecting Antwerp city boundaries (or just download the whole Belgium dataset; small enough)
- **Output (raw):** `raw/statbel_sectors_<YYYY-MM-DD>.gpkg`
- **Output (cleaned):** `cleaned/statistical_sectors.gpkg`
- **Output (reviewed):** `reviewed/statistical_sectors.gpkg`
- **Cleaning steps:**
  - Filter to sectors intersecting AOI
  - Verify EPSG:31370
  - Keep canonical sector code as both `id` and `source_id` (it's stable from Statbel)
- **Dependency:** AOI

### [ ] 9. Population per statistical sector

CSV, joined to sectors.

- **Catalogue id:** `statbel_population`
- **Endpoint:** `portal` — download CSV from Statbel
- **Output (raw):** `raw/statbel_population_<YYYY>.csv`
- **Output (cleaned):** merged into `cleaned/statistical_sectors.gpkg` as additional columns
- **Output (reviewed):** `reviewed/statistical_sectors.gpkg` (now with population)
- **Cleaning steps:**
  - Join CSV to sector polygons on sector code
  - Add columns: `total_population`, `pop_0_17`, `pop_18_64`, `pop_65_plus` (whichever age bands are published)
  - Verify the year of the population data matches what's in the metadata
- **Dependency:** statistical_sectors (cleaned)

### [ ] 10. Landgebruikskaart (Flemish land use raster)

- **Catalogue id:** `landuse_vlaanderen`
- **Endpoint:** `download` — 10m raster
- **Output (raw):** `raw/landuse_<YYYY-MM-DD>.tif`
- **Output (cleaned):** `cleaned/land_use.tif`
- **Output (reviewed):** `reviewed/land_use.tif`
- **Cleaning steps:**
  - Clip to AOI + 200m buffer
  - Keep classification codes; document the legend in a sidecar (`land_use_legend.yaml`)
  - Write as COG
- **Dependency:** AOI

---

## Tier 3 — Greenspace, water, energy potential

### [ ] 11. Antwerp greenspace polygons

- **Catalogue id:** `antwerp_open_data` (use the city portal)
- **Endpoint:** `portal` — search for parks / greenspace / `groen` datasets
- **Output (raw):** `raw/antwerp_greenspace_<YYYY-MM-DD>.gpkg`
- **Output (cleaned):** `cleaned/greenspace.gpkg`
- **Output (reviewed):** `reviewed/greenspace.gpkg`
- **Cleaning steps:**
  - Filter to AOI
  - Normalise type (park, garden, playground, etc.)
  - Compute area_m2
- **Dependency:** AOI
- **Notes:** Antwerp publishes multiple greenspace layers (managed parks, ecological zones, etc.). Either combine into one or keep separate — decide and document.

### [ ] 12. BWK (Biological Valuation Map)

- **Catalogue id:** `bwk`
- **Endpoint:** `wfs`
- **Filter:** bbox = AOI + 200m
- **Output (raw):** `raw/bwk_<YYYY-MM-DD>.gpkg`
- **Output (cleaned):** `cleaned/bwk.gpkg`
- **Output (reviewed):** `reviewed/bwk.gpkg`
- **Cleaning steps:**
  - Clip to AOI
  - Keep BWK biotope codes; document the legend in a sidecar (`bwk_legend.yaml`)
  - Compute area_m2
- **Dependency:** AOI

### [ ] 13. VHA (Flemish hydrography)

- **Catalogue id:** `vha`
- **Endpoint:** `wfs`
- **Filter:** bbox = AOI + 500m (water features can extend beyond)
- **Output (raw):** `raw/vha_<YYYY-MM-DD>.gpkg`
- **Output (cleaned):** `cleaned/water.gpkg`
- **Output (reviewed):** `reviewed/water.gpkg`
- **Cleaning steps:**
  - Clip to AOI + buffer (water continuity matters for any flow analysis)
  - Separate watercourses (lines) from water bodies (polygons) into two layers in the GPKG
  - Normalise category fields
- **Dependency:** AOI

### [ ] 14. Flood-prone areas

- **Catalogue id:** `overstromingsgevoelige_gebieden`
- **Endpoint:** `wfs` or `download`
- **Filter:** AOI + 200m
- **Output (raw):** `raw/flood_zones_<YYYY-MM-DD>.gpkg`
- **Output (cleaned):** `cleaned/flood_zones.gpkg`
- **Output (reviewed):** `reviewed/flood_zones.gpkg`
- **Cleaning steps:**
  - Clip to AOI
  - Keep hazard category attribute (effectively a hazard class: low / medium / high or similar)
- **Dependency:** AOI

### [ ] 15. Adressenregister

- **Catalogue id:** `adressenregister`
- **Endpoint:** `wfs`
- **Filter:** bbox = AOI envelope (no buffer needed — addresses are point features inside buildings)
- **Output (raw):** `raw/addresses_<YYYY-MM-DD>.gpkg`
- **Output (cleaned):** `cleaned/addresses.gpkg`
- **Output (reviewed):** `reviewed/addresses.gpkg`
- **Cleaning steps:**
  - Filter to AOI
  - Optionally spatial-join to nearest building footprint (adds `building_id` column) — useful for the synthetic population work later
- **Dependency:** AOI, buildings (if doing the join)

### [ ] 16. Cadastral parcels

- **Catalogue id:** to confirm — likely served via the GRB bundle as `Adp` (Administratief Perceel)
- **Endpoint:** `wfs`
- **Filter:** bbox = AOI envelope
- **Output (raw):** `raw/parcels_<YYYY-MM-DD>.gpkg`
- **Output (cleaned):** `cleaned/parcels.gpkg`
- **Output (reviewed):** `reviewed/parcels.gpkg`
- **Cleaning steps:**
  - Filter to AOI
  - Keep parcel id as source_id
  - Compute area_m2
- **Dependency:** AOI

### [ ] 17. Zonnekaart (rooftop solar potential)

- **Catalogue id:** `zonnekaart` (when added — currently in `datasets_to_add.txt`)
- **Endpoint:** to confirm
- **Output (raw):** `raw/zonnekaart_<YYYY-MM-DD>.gpkg` or `.tif`
- **Output (cleaned):** `cleaned/solar_potential.gpkg` (per-building) or `.tif` (raster)
- **Output (reviewed):** `reviewed/solar_potential.gpkg`
- **Cleaning steps:**
  - If per-building: spatial-join to GRB buildings, store kWh/year potential per building
  - Verify it covers the AOI (it does for all of Flanders)
- **Dependency:** buildings (cleaned), if per-building data

### [ ] 18. Warmtenet-potentiaalkaart (heat demand / heat network potential)

- **Catalogue id:** `warmtenet_potentiaal` (when added)
- **Endpoint:** to confirm
- **Output (raw):** `raw/warmtenet_<YYYY-MM-DD>.{gpkg|tif}`
- **Output (cleaned):** `cleaned/heat_demand.tif` or `.gpkg`
- **Output (reviewed):** `reviewed/heat_demand.tif`
- **Cleaning steps:**
  - Clip to AOI + 200m
  - Document units (likely MWh/ha/year or similar) in metadata
- **Dependency:** AOI

---

## Tier 4 — Environmental layers (paired with specific modules)

Lower priority — fetch when the corresponding module is being built.

### [ ] 19. Strategic noise maps (`geluidskaarten`)

When noise module starts. Multiple sub-layers (road, rail, industry).

### [ ] 20. IRCELINE air quality (RIO-IFDM rasters)

When air quality module starts.

### [ ] 21. Copernicus Tree Cover Density

For canopy fraction beyond the municipal tree inventory.

### [ ] 22. Copernicus Imperviousness

For stormwater modelling.

---

## Tier 5 — Document the gap, don't fetch

Add a `tbd_<gap>.md` file in the data folder explaining what's available and what isn't.

### [ ] Power grid (`tbd_power_grid.md`)

Distribution-level grid data (Fluvius) is not openly available. High-voltage transmission (Elia) is partially open. Document this; revisit when partnerships allow.

### [ ] Sewers (`tbd_sewers.md`)

Aquafin and Water-link own this data; not openly available. Document the gap.

---

## Practical workflow per dataset

For each item above, the workflow is:

1. **Ingest:** run the ingest script. Outputs land in `raw/`. Update `_ingest_log.yaml`.
2. **Clean:** run the cleaning script. Outputs land in `cleaned/`. Cleaning log saved alongside.
3. **Review (manual):** open `cleaned/<dataset>.gpkg` (or `.tif`) in QGIS. Sanity-check:
   - Coverage matches AOI
   - Geometries look sensible
   - Attributes are populated
   - Counts are reasonable
4. **Promote:** if review passes, copy `cleaned/<dataset>.{gpkg,tif}` to `reviewed/`. Update `meta.yaml` with `reviewed_at`, `reviewer`, `notes`.
5. **Mark complete:** check the box in this document.

---

## Per-dataset cleaning script template

Each cleaning script follows the same skeleton:

```python
# src/clean/<dataset>.py
"""Clean <dataset> for <city>/<neighbourhood>.

Decisions:
- [decision 1]
- [decision 2]
...
"""

def clean(raw_path: Path, aoi: Polygon, output_path: Path) -> CleaningLog:
    """Read raw, clean, write to output_path. Return log of what happened."""
    ...
```

The `CleaningLog` records: rows in, rows out, rows dropped (with reasons), columns added, anomalies. Saved alongside the output.

---

## Notes on AOI buffering

A consistent buffering convention saves headaches:

- **Tier 1 raster fetches (terrain):** AOI + 200m buffer
- **Tier 1 vector fetches (buildings):** AOI + 100m buffer for fetch, AOI strict for reviewed output
- **Roads, water:** AOI + 200m+ for fetch (these need context), AOI + buffer for reviewed (clipping too tight breaks routing/flow)
- **Single-feature lookups (sectors, parcels, addresses):** strict AOI is fine

The buffer-on-fetch + clip-on-reviewed pattern means raw data has context, but the reviewed layer is exactly the neighbourhood. Modules can then load reviewed data confident there's no leakage.

---

## What this checklist does not do

- It doesn't write the actual code. Claude Code or you do that, using this as the spec.
- It doesn't dictate the cleaning logic in detail — only flags decisions. Those decisions get made and documented in the cleaning scripts themselves.
- It doesn't include power grid or sewer fetches because those data don't exist openly.

---

## Suggested sequencing

If picking up this checklist over multiple sessions:

**Session 1:** AOI + Tier 1 (steps 0–4). End state: terrain and buildings reviewable.
**Session 2:** Tier 2 (steps 6–10). End state: roads, trees, sectors, population, land use ready.
**Session 3:** Tier 3 greenspace + water (steps 11–14).
**Session 4:** Tier 3 misc (steps 15–18).
**Session 5+:** Tier 4 as modules need them.

Realistic time estimate: each session is roughly half a day to a full day of focused work, including the manual review step.
