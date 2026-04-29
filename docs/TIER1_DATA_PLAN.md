# Tier 1 Data Acquisition Plan — Haringrode

**Status:** Draft for approval
**Author:** Claude
**Date:** 2026-04-29

This plan covers the next wave of data acquisition to enable environmental and energy performance analysis modules.

---

## Overview

Five priority datasets to fetch:

1. **Solar potential** (Zonnekaart) → augment buildings
2. **Noise exposure** (Strategic noise maps) → new standalone dataset
3. **Water features** (VHA) → new standalone dataset
4. **Flood zones** → new standalone dataset
5. **Building age** (from cadastre or EPC) → augment buildings

---

## 1. Solar Potential (Zonnekaart)

### What it is
Rooftop solar irradiation potential in kWh/m²/year. Essential for renewable energy analysis.

### Source
- **Catalogue ID:** `zonnekaart` (to be added)
- **Provider:** Vlaanderen/3E
- **Format:** Likely per-building vector OR raster
- **Coverage:** All of Flanders
- **Resolution:** Building-level or 1m raster

### Fetch approach
**Option A (preferred):** If available as per-building data
- WFS or download portal
- Join to buildings on building ID or spatial join

**Option B:** If only available as raster
- Download raster tiles for AOI
- Zonal statistics per building footprint
- Extract mean/max irradiation

### Integration strategy
**Augment buildings dataset:**
- Add columns to `buildings.gpkg`:
  - `solar_irradiation_kwh_m2_year` (mean for roof)
  - `solar_potential_kwh_year` (total: irradiation × roof_area × efficiency_factor)
  - `solar_suitability` (categorical: excellent/good/moderate/poor based on threshold)

### Decisions needed
- [ ] Check if Zonnekaart exists in catalogue (it's in `datasets_to_add.txt`)
- [ ] Determine if per-building or raster format
- [ ] Define suitability thresholds (e.g., >900 kWh/m²/year = excellent)

### Cleaning script
`src/clean/buildings_solar.py` — loads buildings, joins solar data, adds columns, overwrites buildings.gpkg

---

## 2. Strategic Noise Maps (Geluidskaarten)

### What it is
Noise levels (Lden, Lnight) from road, rail, and industry sources. Critical for comfort/health analysis.

### Source
- **Catalogue ID:** `geluidskaarten`
- **Provider:** Flemish government (Departement Omgeving)
- **Format:** Raster (5m or 10m resolution) + vector contours
- **Metrics:** Lden (day-evening-night), Lnight
- **Sources:** Road, rail, industry (separate layers)

### Fetch approach
1. Check catalogue for WMS/WFS or download endpoints
2. Download raster tiles for AOI + buffer
3. Fetch all source types (road, rail, industry)

### Integration strategy
**New standalone dataset: `noise_exposure.gpkg`**

Two possible schemas:

**Option A: Point grid**
- Regular point grid (e.g., 20m spacing)
- Sample noise values at each point
- Columns: `noise_road_lden`, `noise_rail_lden`, `noise_industry_lden`, `noise_total_lden`

**Option B: Building façades**
- Sample noise at building centroids or façade points
- Link to building ID
- Store in `buildings.gpkg` as additional columns

**Recommendation:** Option A (point grid) for flexibility + Option B columns in buildings for quick access.

### Cleaning script
- `src/ingest/noise.py` — fetch rasters
- `src/clean/noise.py` — create point grid, sample values, save to `reviewed/noise_exposure.gpkg`
- `src/clean/buildings_noise.py` — add noise columns to buildings (mean at building location)

### Decisions needed
- [ ] Confirm noise map availability for Antwerp
- [ ] Choose point grid spacing (10m? 20m?)
- [ ] Define exposure thresholds (WHO guidelines: Lden >55 dB = significant)

---

## 3. Water Features (VHA - Flemish Hydrography)

### What it is
Watercourses (rivers, streams) and water bodies (ponds, lakes). Blue-green infrastructure baseline.

### Source
- **Catalogue ID:** `vha`
- **Provider:** Vlaanderen
- **Format:** WFS, vector (lines + polygons)
- **Coverage:** All of Flanders

### Fetch approach
1. WFS query with bbox = AOI + 500m buffer (water extends beyond blocks)
2. Fetch watercourses (LineString) and water bodies (Polygon) separately
3. Store both in a single GPKG with layer separation

### Integration strategy
**New standalone dataset: `water.gpkg`** (multi-layer GeoPackage)

**Layers:**
- `watercourses` — rivers, streams, canals (LineString)
  - Columns: `id`, `source_id`, `name`, `category` (e.g., river/stream/canal), `width_m`
- `water_bodies` — ponds, lakes, reservoirs (Polygon)
  - Columns: `id`, `source_id`, `name`, `category`, `area_m2`

### Cleaning script
- `src/ingest/vha.py` — fetch from WFS
- `src/clean/vha.py` — clean, normalize categories, clip to AOI + buffer, save to `reviewed/water.gpkg`

### Decisions needed
- [ ] Buffer size (500m reasonable?)
- [ ] Category normalization (map VHA types to simple river/stream/canal/pond/lake)

---

## 4. Flood Zones (Overstromingsgevoelige Gebieden)

### What it is
Flood risk classification polygons. Climate adaptation and stormwater management baseline.

### Source
- **Catalogue ID:** `overstromingsgevoelige_gebieden`
- **Provider:** Vlaanderen (Departement Omgeving)
- **Format:** WFS, vector (Polygon)
- **Classes:** Likely high/medium/low risk or return periods (T10, T100, etc.)

### Fetch approach
1. WFS query with bbox = AOI + 200m buffer
2. Download flood risk polygons
3. Check if multiple layers (different scenarios/return periods)

### Integration strategy
**New standalone dataset: `flood_zones.gpkg`**

**Columns:**
- `id`, `source_id`, `geometry`
- `risk_category` — normalized to high/medium/low
- `return_period_years` — if available (e.g., 10, 100, 1000)
- `area_m2`

**Also augment buildings:**
- Spatial join to determine if building intersects flood zone
- Add column to `buildings.gpkg`:
  - `flood_risk` (categorical: high/medium/low/none)

### Cleaning script
- `src/ingest/flood_zones.py` — fetch from WFS
- `src/clean/flood_zones.py` — normalize categories, clip, save to `reviewed/flood_zones.gpkg`
- `src/clean/buildings_flood.py` — spatial join, add `flood_risk` to buildings

### Decisions needed
- [ ] Check if data exists for Antwerp (coastal/fluvial flooding)
- [ ] Understand classification schema (risk categories vs. return periods)

---

## 5. Building Age (Cadastre or EPC)

### What it is
Construction year for each building. Enables:
- Material assumptions (age → construction practices)
- Embodied carbon estimation
- Renovation priority
- Energy performance correlation

### Source options

**Option A: Cadastral data (Kadaster/GRB Adp)**
- May include construction year
- **Catalogue ID:** Check if in GRB bundle or separate cadastre dataset
- **Format:** WFS, vector
- **Join:** Spatial join to buildings

**Option B: EPC (Energy Performance Certificates)**
- Includes construction year + energy data (U-values, heating, EPC rating)
- **Source:** Flanders EPC database (check if openly available)
- **Format:** Unknown (API? Download?)
- **Join:** On address or building ID

**Option C: Infer from other sources**
- OSM `building:year` tags (sparse coverage)
- Visual inspection + ML on aerial imagery (labor-intensive)

### Fetch approach
1. **First:** Check if GRB 3D or cadastre includes construction year
2. **Second:** Check EPC database availability (may require partnership/API key)
3. **Fallback:** OSM tags where available

### Integration strategy
**Augment buildings dataset:**
- Add columns to `buildings.gpkg`:
  - `construction_year` (integer, nullable)
  - `construction_era` (categorical: pre-1945, 1945-1970, 1970-1990, 1990-2010, post-2010)
  - If EPC available:
    - `epc_label` (A+, A, B, C, D, E, F)
    - `heating_type` (gas, electric, heat pump, etc.)
    - `insulation_level` (good/moderate/poor)

### Cleaning script
- `src/ingest/building_age.py` — fetch cadastre or EPC data
- `src/clean/buildings_age.py` — join to buildings, add columns, classify eras

### Decisions needed
- [ ] Check GRB/cadastre for construction year field
- [ ] Investigate EPC database access (open data? API?)
- [ ] Define construction era bins

---

## Execution Sequence

Recommended order (considering dependencies):

### Phase 1: Standalone datasets (no dependencies)
1. **VHA (water)** — straightforward WFS fetch
2. **Flood zones** — straightforward WFS fetch
3. **Noise maps** — fetch and create point grid

### Phase 2: Building augmentation (depends on buildings being stable)
4. **Solar potential** — join to buildings
5. **Building age** — join to buildings

### Phase 3: Building enrichment from standalone
6. **Flood risk column** — spatial join from flood_zones to buildings
7. **Noise columns** — sample from noise grid to buildings

---

## Data Storage

After completion, the `reviewed/` directory will contain:

**Vector datasets:**
- `buildings.gpkg` — **ENRICHED** with solar, age, flood_risk, noise_lden
- `water.gpkg` — watercourses + water_bodies (multi-layer)
- `flood_zones.gpkg` — flood risk polygons
- `noise_exposure.gpkg` — point grid with noise levels

**Raster datasets (if needed):**
- `noise_road_lden.tif` — road noise raster
- `noise_rail_lden.tif` — rail noise raster
- `solar_irradiation.tif` — solar potential raster (if not per-building)

---

## Schema Changes

### Buildings (augmented columns)

| Column                    | Type      | Unit         | Description                                |
|---------------------------|-----------|--------------|--------------------------------------------|
| `solar_irradiation_kwh_m2`| `float?`  | kWh/m²/year  | Mean rooftop solar irradiation. Nullable.  |
| `solar_potential_kwh`     | `float?`  | kWh/year     | Total annual potential (area × irradiation × 0.15). Nullable. |
| `solar_suitability`       | `str?`    | —            | excellent/good/moderate/poor. Nullable.    |
| `construction_year`       | `int?`    | —            | Year built. Nullable.                      |
| `construction_era`        | `str?`    | —            | pre-1945, 1945-1970, etc. Nullable.        |
| `flood_risk`              | `str?`    | —            | high/medium/low/none. Nullable.            |
| `noise_lden_db`           | `float?`  | dB           | Total noise exposure (Lden). Nullable.     |
| `epc_label`               | `str?`    | —            | A+, A, B, C, D, E, F (if EPC available).   |

### New datasets

**Noise Exposure:**
- Point grid, 20m spacing
- Columns: `id`, `x`, `y`, `geometry`, `noise_road_lden`, `noise_rail_lden`, `noise_industry_lden`, `noise_total_lden`

**Water:**
- Watercourses: `id`, `source_id`, `name`, `category`, `width_m`, `geometry` (LineString)
- Water bodies: `id`, `source_id`, `name`, `category`, `area_m2`, `geometry` (Polygon)

**Flood Zones:**
- `id`, `source_id`, `risk_category`, `return_period_years`, `area_m2`, `geometry` (Polygon)

---

## Known Challenges

1. **Solar data format uncertainty** — need to check if Zonnekaart is per-building or raster
2. **EPC data access** — may not be openly available; need to investigate
3. **Noise map resolution** — if too coarse (e.g., 100m), façade-level analysis not feasible
4. **Temporal mismatch** — solar maps may be outdated, building age may conflict with GRB dates
5. **Construction year gaps** — many buildings may lack construction year data

---

## Success Criteria

After Tier 1 completion, the system should support:

✅ **Solar potential module** — compute PV generation for any building or scenario
✅ **Noise exposure module** — assess acoustic comfort at building/street level
✅ **Flood risk analysis** — identify vulnerable buildings, design drainage
✅ **Blue-green infrastructure** — map water features, plan interventions
✅ **Embodied carbon estimation** — use building age as proxy for materials

---

## Next Steps

1. **Catalogue check** — verify all datasets exist and get endpoints
2. **Fetch order** — start with VHA (easiest) to validate pipeline
3. **Schema finalization** — review proposed columns, adjust as needed
4. **Ingest scripts** — write fetch scripts for each dataset
5. **Cleaning scripts** — process and integrate data
6. **Meta.yaml updates** — document sources and decisions
7. **SCHEMA.md updates** — document new columns and datasets

---

**Approval needed before proceeding:** Review this plan and confirm approach for each dataset.
