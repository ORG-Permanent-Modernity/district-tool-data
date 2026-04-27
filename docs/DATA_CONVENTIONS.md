# Data folder conventions

This document describes the layout of `district-tool-data/` on the shared drive. It applies to everyone — devs, reviewers, anyone touching the data folder.

> **Note:** This file lives in `district-tool-data/CONVENTIONS.md` (on the shared drive), not in the model repo. The repo references this document but does not own the data.

## Folder structure

```
district-tool-data/
├── README.md                     ← what's in here, where to start
├── CONVENTIONS.md                ← this file
├── <city>/
│   ├── _ingest_log.yaml          ← record of every ingest run (city-wide)
│   └── <neighbourhood>/
│       ├── aoi.gpkg              ← neighbourhood boundary, EPSG:31370
│       ├── meta.yaml             ← what datasets exist, their versions
│       ├── raw/                  ← fetched from source, untouched
│       ├── cleaned/              ← after automated cleaning
│       └── reviewed/             ← human-reviewed, application-readable
└── shared/
    ├── materials.yaml            ← shared material library (later)
    └── vegetation.yaml           ← shared vegetation library (later)
```

Cities are lowercase: `antwerp`, `ghent`, `brussels`. Neighbourhoods are lowercase, no spaces: `zurenborg`, `eilandje`, `borgerhout_intra_muros`.

## Formats

- **Vectors:** GeoPackage (`.gpkg`). One layer per file by default. Multiple layers in one file when they belong together (e.g. `water.gpkg` with `watercourses` and `water_bodies` layers).
- **Rasters:** GeoTIFF, preferably Cloud-Optimized GeoTIFF (COG) for future-friendliness.
- **Tabular non-spatial:** CSV with documented columns, joined to spatial data during cleaning.
- **Metadata:** YAML.

## Coordinate reference system

**EPSG:31370 (Belgian Lambert 72) for everything.** No exceptions. Reproject during cleaning if the source is in something else.

The loader's contract is "everything is 31370". Modules and the API rely on this. Mixed CRSes inside the data pipeline produce silent bugs.

## The raw → cleaned → reviewed pipeline

### `raw/`

Fetched from source. Never edited. If the source data needs re-fetching, write a new file with a new date suffix — never overwrite.

Filename convention: `<dataset>_<YYYY-MM-DD>.gpkg` or `.tif`.

Examples:
- `raw/grb_gebouwen_2026-04-23.gpkg`
- `raw/dhm_dsm_2026-04-23/<tile_id>.tif`

### `cleaned/`

Output of automated cleaning scripts. Each file has a corresponding cleaning log:

- `cleaned/buildings.gpkg`
- `cleaned/buildings.cleaning_log.yaml`

The log records: rows in, rows out, rows dropped (with reasons), columns added, anomalies. If the script ran more than once, only the most recent log is kept.

`cleaned/` is updateable. Re-running the cleaning script overwrites `cleaned/<dataset>.gpkg`. The `raw/` files used as input are pinned in the cleaning log.

### `reviewed/`

Human-promoted, application-readable. The loader reads ONLY from `reviewed/`.

Filename convention: `<dataset>.gpkg` (no date — this is the current reviewed version).

Promotion process:
1. Open `cleaned/<dataset>.gpkg` in QGIS.
2. Sanity-check: coverage matches AOI, geometries are sensible, attributes are populated, counts are reasonable.
3. Read `cleaned/<dataset>.cleaning_log.yaml` and verify nothing surprising.
4. If happy: copy `cleaned/<dataset>.gpkg` to `reviewed/<dataset>.gpkg`.
5. Update `meta.yaml` (see below).
6. Optionally archive the previous reviewed version to `reviewed/_archive/<dataset>_<YYYY-MM-DD>.gpkg` before overwriting.

## `meta.yaml` per neighbourhood

Records what's been reviewed and promoted. The application reads this at startup to know what's available.

Schema:

```yaml
buildings:
  source: grb_gebouwen           # catalogue id from the model repo's catalogue/
  source_version: "2026-04-15"   # provider-supplied version, where known
  ingested_at: "2026-04-18"      # date raw/ was populated
  cleaned_at: "2026-04-19"       # date cleaning script last ran
  reviewed_at: "2026-04-20"      # date promoted to reviewed/
  reviewer: "John"               # who promoted
  notes: "Spot-checked against cadastre; heights look sensible."
  row_count: 1487                # for quick reference
  cleaning_decisions:            # high-level summary, full detail in cleaning_log
    - "Dropped buildings <10m² (134 features)"
    - "Computed heights from DHM nDSM (median per footprint)"
    - "Initialised use_hint as 'unknown'"

terrain_dsm:
  source: dhm_vlaanderen_dsm
  source_version: "DHM-II 2014"
  ingested_at: "2026-04-17"
  cleaned_at: "2026-04-17"
  reviewed_at: "2026-04-18"
  reviewer: "John"
  notes: "Mosaicked from 4 source tiles; clipped to AOI + 200m buffer."
  resolution_m: 1.0
```

Use the dataset id as the top-level key. Match the loader's method names where possible (`buildings`, `roads`, `trees`, `terrain_dsm`, etc.).

## `_ingest_log.yaml` per city

Tracks every ingest run, regardless of success. Append-only.

Schema:

```yaml
runs:
  - run_id: "2026-04-18T10:23:00Z-grb_gebouwen-zurenborg"
    dataset: grb_gebouwen
    neighbourhood: zurenborg
    started_at: "2026-04-18T10:23:00Z"
    finished_at: "2026-04-18T10:24:12Z"
    status: success
    rows_fetched: 1502
    output_path: "antwerp/zurenborg/raw/grb_gebouwen_2026-04-18.gpkg"
    notes: "WFS request succeeded after one retry on timeout."

  - run_id: "2026-04-18T10:25:00Z-dhm_dsm-zurenborg"
    dataset: dhm_dsm
    neighbourhood: zurenborg
    started_at: "2026-04-18T10:25:00Z"
    finished_at: "2026-04-18T10:31:45Z"
    status: success
    tiles_fetched: 4
    output_path: "antwerp/zurenborg/raw/dhm_dsm_2026-04-18/"
```

Failed runs are also recorded with `status: failed` and a `reason`.

## Things you should NOT do

**Don't edit files in `raw/`.** Ever. Re-fetch with a new date if needed.

**Don't bypass `reviewed/` and have anything read from `cleaned/` or `raw/`.** Modules rely on the review checkpoint having happened. If you're tempted to "just for now" point at unreviewed data, fix the review process instead.

**Don't store project outputs (analysis results, scenarios) in this folder.** This folder is for ingested reference data only. Project outputs go in a separate folder structure (TBD).

**Don't commit data to git.** This folder is on the shared drive specifically because it's not git-versioned. Even small test fixtures: keep them inside the model repo's `tests/fixtures/`, not here.

**Don't share `cleaned/` files with non-team members.** They haven't been reviewed; they may contain artefacts. Share `reviewed/` if needed.

## When in doubt

- Look at how an existing dataset is structured.
- Read the relevant section of `src/data/SCHEMA.md` in the model repo.
- Ask before bending the rules.
