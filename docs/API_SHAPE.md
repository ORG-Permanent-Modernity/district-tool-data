# API Shape — District Analysis Tool (v0)

**Status:** Draft for discussion with David
**Owner:** John
**Last revised:** April 2026

This document describes the HTTP API that the frontend consumes. It is the contract between the Python backend and the frontend — once agreed, both sides can work independently against it.

This is a living document for v0 (Antwerp / Zurenborg). Endpoints will grow as modules are added. Breaking changes to existing endpoints require version bumps (`/api/v1/` → `/api/v2/`).

---

## Conventions

- **Base URL:** `/api/v1/` (local dev: `http://localhost:8000/api/v1/`)
- **Coordinate reference system:** All geometries in responses are **EPSG:4326 (WGS84 lat/lon)**. Internal storage is EPSG:31370; the API reprojects at the boundary.
- **Format:** JSON throughout. Geometry responses are **GeoJSON FeatureCollections**.
- **Provenance:** Every response includes a `metadata` block with source, version, and review timestamps.
- **Errors:** Standard HTTP status codes. Error body: `{"error": "message", "detail": "..."}`.
- **Units:** Metric. Distances in metres, areas in square metres, heights in metres above ground unless otherwise noted.
- **CORS:** Enabled for the frontend's dev origin.
- **Authentication:** Not yet. Will be added when the tool moves beyond internal use.

---

## Endpoints

### Discovery

#### `GET /cities`

List available cities.

```json
{
  "cities": [
    {"id": "antwerp", "name": "Antwerpen", "country": "BE"}
  ]
}
```

#### `GET /cities/{city}/neighbourhoods`

List neighbourhoods available for a city.

```json
{
  "city": "antwerp",
  "neighbourhoods": [
    {"id": "zurenborg", "name": "Zurenborg", "description": "Historical residential district"}
  ]
}
```

#### `GET /cities/{city}/neighbourhoods/{neighbourhood}`

Metadata for a single neighbourhood, including the AOI polygon.

```json
{
  "city": "antwerp",
  "neighbourhood": "zurenborg",
  "name": "Zurenborg",
  "aoi": {
    "type": "Feature",
    "geometry": {"type": "Polygon", "coordinates": [...]},
    "properties": {}
  },
  "available_datasets": ["buildings", "roads", "trees", "terrain"],
  "building_count": 1487,
  "area_m2": 625000
}
```

---

### Reference data

All reference-data endpoints return GeoJSON FeatureCollections in EPSG:4326.

#### `GET /cities/{city}/neighbourhoods/{n}/buildings`

All building footprints in the neighbourhood, with heights and attributes.

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {"type": "Polygon", "coordinates": [[[4.42, 51.21], ...]]},
      "properties": {
        "id": "b-1f3a7d8c...",
        "source_id": "12345",
        "height_m": 12.3,
        "height_source": "dhm_derived",
        "roof_type": "pitched",
        "area_m2": 87.2,
        "estimated_storeys": 4,
        "use_hint": "residential"
      }
    }
  ],
  "metadata": {
    "dataset": "buildings",
    "source": "grb_gebouwen",
    "source_version": "2026-04-15",
    "reviewed_at": "2026-04-20",
    "reviewer": "John",
    "count": 1487
  }
}
```

#### `GET /cities/{city}/neighbourhoods/{n}/roads`

Road network. Same structure as buildings.

Properties per feature:
- `id`, `source_id`
- `road_class` — `highway`, `arterial`, `local`, `cycleway`, `pedestrian`
- `speed_kmh` — posted limit, or null
- `direction` — `both`, `forward`, `backward`
- `name` — street name, or null

#### `GET /cities/{city}/neighbourhoods/{n}/trees`

Municipal tree inventory points.

Properties per feature:
- `id`, `source_id`
- `species` — Latin name, nullable
- `common_name` — Dutch name, nullable
- `planted_year` — nullable
- `diameter_class` — source category
- `estimated_crown_radius_m` — heuristic from diameter class

---

### Raster data

Terrain rasters are served via a tile endpoint rather than a single blob — this is the only sensible pattern for rasters at any useful resolution.

#### `GET /cities/{city}/neighbourhoods/{n}/terrain/{kind}/{z}/{x}/{y}.png`

XYZ tile of terrain data, styled for visualisation.

- `kind` — one of `dsm`, `dtm`, `ndsm`
- `z`, `x`, `y` — standard slippy map tile indices
- Returns a 256×256 PNG with elevation values colour-mapped

For analysis (not display), a separate endpoint returns raw values:

#### `GET /cities/{city}/neighbourhoods/{n}/terrain/{kind}/values`

```
Query: ?bbox=lng_min,lat_min,lng_max,lat_max  (EPSG:4326)
```

Returns a NumPy-serialised array (or GeoTIFF) for the requested bbox, in EPSG:31370. Primarily for backend-to-backend or scripted use. David's frontend would use the tile endpoint, not this one.

*(Tile endpoint is v0.2+ — for v0.1, a static GeoTIFF download is acceptable placeholder.)*

---

### Analysis (placeholder for modules)

These don't exist yet, but documenting the expected shape so David can plan the UI.

#### `POST /cities/{city}/neighbourhoods/{n}/analysis/solar`

Body: analysis parameters (date, time, resolution).

Response: GeoJSON with solar radiation values per cell or per building face.

#### `POST /cities/{city}/neighbourhoods/{n}/analysis/comfort`

Body: UTCI parameters (date, time, met/clo values, air temp override).

Response: GeoJSON with UTCI values per ground-grid cell.

Further analysis endpoints follow the same pattern: `POST` with parameters, response is GeoJSON + metadata.

---

## Status codes

- `200 OK` — success
- `400 Bad Request` — invalid parameters
- `404 Not Found` — unknown city, neighbourhood, or dataset
- `500 Internal Server Error` — backend failure (cleaning, ingestion, or loader issue)

---

## What's NOT in v0

Documented explicitly so expectations are clear:

- **User-drawn AOIs.** The AOI is the full neighbourhood. Frontend sends no bbox to filter.
- **Scenarios / edits.** No `POST /scenarios` yet. Design-exploration is a later deliverable.
- **Auth.** Open API for now. Lock down when deploying beyond internal use.
- **Pagination.** Neighbourhoods are small enough that full dumps are fine. Revisit if a request exceeds ~50k features.
- **Streaming / server-sent events.** Analysis is synchronous for v0. Long-running analyses get async job queue later.

---

## Questions for David

Things I've assumed that may not match what he's building:

1. Is **GeoJSON** the right format for vector data, or does the frontend prefer **vector tiles (MVT/PBF)**? MVT is more performant for large layers but heavier to generate server-side. For 1500 buildings, GeoJSON is fine.
2. Does the frontend expect **EPSG:4326** (standard for MapLibre GL) or **EPSG:3857** (Web Mercator, also standard for some map libraries)? 4326 is my assumption.
3. For terrain, does the frontend need **styled PNG tiles** (we do the colour mapping server-side) or **raw elevation tiles** (frontend colour-maps)? PNG tiles are simpler initially.
4. Does the API need **CORS** configured for any specific origins beyond localhost?

---

## Changelog

- *v0 (April 2026):* initial draft.
