# CLAUDE.md — District Analysis Tool

This file tells any Claude instance how to work in this repo. Read this first before doing anything.

## What this project is

A web-based design-exploration tool for the environmental and energy performance of European urban blocks. Users load a block, inspect baseline performance across a focused set of metrics, and modify the design (add buildings, change materials, plant vegetation) to see how performance shifts. Side-by-side scenario comparison is the core interaction.

Target user (v1): internal ORG architects and urbanists during early- and mid-stage design.
Target scale: city block (~10–50 buildings, ~200m extent).
Geographic focus (v1): Antwerp, then Ghent, then Brussels.

For more on positioning, scope, and design philosophy, see `docs/CHARTER.md`.

## Repo structure

```
.
├── CLAUDE.md                    ← this file
├── README.md                    ← human-facing
├── src/
│   ├── data/
│   │   ├── loader.py            ← THE data access contract — do not break
│   │   ├── catalogue_access.py  ← wrapper for the externally-located catalogue
│   │   └── SCHEMA.md            ← canonical data schema documentation
│   ├── ingest/                  ← per-dataset fetch scripts (catalogue → raw)
│   ├── clean/                   ← per-dataset cleaning scripts (raw → cleaned)
│   ├── modules/                 ← analysis modules (solar, comfort, noise, ...)
│   └── api/                     ← FastAPI endpoints (later)
├── docs/
│   ├── API_SHAPE.md             ← contract between backend and frontend
│   ├── FETCH_CHECKLIST.md       ← prioritised dataset fetch list
│   ├── CHARTER.md               ← project charter / scope
│   ├── DATA_CONVENTIONS.md      ← raw/cleaned/reviewed pipeline rules
│   └── prompts/                 ← task-specific prompts to paste into Claude Code
└── tests/
```

The geo-catalogue is NOT in this repo. It lives in its own repo, cloned locally and referenced via the `CATALOGUE_PATH` env var. See "Cardinal rule 2" below.

Data also does NOT live in this repo. The data root is on a shared drive, configured via `DATA_ROOT`.

## Cardinal rules

These rules apply to every session, every task, every change. Violating them is a source of bugs that take weeks to surface.

### 1. The loader is the contract

`src/data/loader.py` defines how the rest of the codebase reads data. Modules, API endpoints, scripts, and notebooks MUST go through `DataLoader`. They MUST NOT read files directly.

If a cleaning script can't produce data matching the schema in `loader.py`, the cleaning script is wrong, not the schema. The schema is the contract; storage and cleaning are implementations.

The schema columns and types are documented in:
- `src/data/loader.py` — docstrings (the machine-readable contract)
- `src/data/SCHEMA.md` — human-readable, with semantics and gotchas

When adding a new dataset, both must be updated.

### 2. Always use the catalogue

The Belgian geospatial catalogue holds every data source's endpoints, licences, and metadata. It lives in its **own repo**, cloned locally and referenced via the `CATALOGUE_PATH` env var.

Every fetch in `src/ingest/*` goes through:

```python
from src.data.catalogue_access import Catalogue
cat = Catalogue()
url = cat.endpoint("grb_gebouwen", "wfs")
```

Hardcoded URLs in ingest code are a bug. If a URL is missing from the catalogue, update the catalogue YAML in the geo-catalogue repo and `git pull` here — don't paper over it inline.

The catalogue is not part of this repo. To set it up:

```bash
git clone git@github.com:ORG/geo-catalogue.git ~/repos/geo-catalogue
# then add CATALOGUE_PATH=/Users/yourname/repos/geo-catalogue to .env
```

See `src/data/catalogue_access.py` for the access layer. Read the catalogue's own `${CATALOGUE_PATH}/CLAUDE.md` for catalogue-specific conventions when editing it.

### 3. EPSG:31370 internally, reproject only at the API boundary

All Belgian datasets are in EPSG:31370 (Belgian Lambert 72). Internal storage, internal computation, and the loader's outputs are all 31370. Reprojection to EPSG:4326 (or 3857) happens in the API layer when serialising to GeoJSON for the web frontend.

Do not mix CRSes inside the data pipeline. Mixed-CRS bugs are silent and painful.

### 4. Raw → cleaned → reviewed; modules read only from reviewed

Per dataset, three stages:

```
raw/        ← fetched from source, untouched
cleaned/    ← after automated cleaning, with cleaning_log.yaml
reviewed/   ← human-reviewed and promoted; this is what the loader reads
```

Never let the application or modules read from `raw/` or `cleaned/`. The loader exposes only `reviewed/`. The review step is a human checkpoint — automated cleaning is not a substitute for it.

### 5. Data does not go in git

This repo holds code, schemas, scripts, and documentation. The data folder (typically tens of GB once populated) lives on a shared drive. The path is configured via the `DATA_ROOT` environment variable.

If you ever consider `git add district-tool-data/...` or similar — stop. There is no scenario where data files belong in the repo.

### 6. Stop and ask when decisions matter

When writing cleaning scripts especially, decisions like "what minimum building area counts" or "how to handle null heights" are domain judgements with downstream effects. Don't pick silently. Ask, document the answer in the cleaning script's docstring, and proceed.

When updating the schema, the API shape, or the loader contract — pause and confirm before committing.

## Configuration

The repo reads two environment variables from `.env`:

```
DATA_ROOT=/path/to/shared-drive/district-tool-data
CATALOGUE_PATH=/Users/yourname/repos/geo-catalogue
```

Both are required. Code that needs them imports from `src/data/catalogue_access.py` (for the catalogue) or directly via `os.getenv("DATA_ROOT")` (for the data root, until a config module exists).

## Data folder structure

Inside `DATA_ROOT`:

```
district-tool-data/
├── README.md                     ← what's here, conventions
├── CONVENTIONS.md                ← raw/cleaned/reviewed pipeline rules
├── antwerp/
│   └── zurenborg/                ← (or whichever neighbourhood)
│       ├── aoi.gpkg              ← neighbourhood boundary, EPSG:31370
│       ├── meta.yaml             ← what datasets exist, their versions
│       ├── _ingest_log.yaml      ← record of every ingest run
│       ├── raw/
│       ├── cleaned/
│       └── reviewed/
└── shared/
    ├── materials.yaml            ← shared material library (later)
    └── vegetation.yaml           ← shared vegetation library (later)
```

The structure is documented in `docs/DATA_CONVENTIONS.md`. New cities and neighbourhoods follow the same shape.

## Working conventions

### Python and dependencies

- Python 3.11+
- Dependency management: `pyproject.toml`, installed via `pip install -e ".[dev]"`
- Spatial stack: GeoPandas, Shapely 2.x, rasterio, pyproj, Fiona
- Web stack (later): FastAPI, pydantic
- Tests: pytest, with `tests/` mirroring `src/` structure

### Style

- Type hints everywhere, including return types
- Docstrings on every public function and class — Google or NumPy style, consistent within a file
- Module-level docstring summarising what the module does
- Decisions documented in code (not just commit messages)

### When adding a new dataset

The full sequence:

1. Confirm the dataset is in the catalogue (or add it). See the catalogue repo's CLAUDE.md.
2. Add a method to `DataLoader` with full docstring describing the schema.
3. Add a section to `src/data/SCHEMA.md` with semantic notes.
4. Write the ingest script in `src/ingest/<dataset>.py`.
5. Write the cleaning script in `src/clean/<dataset>.py`.
6. Run both, sanity-check, then human-review the cleaned output.
7. Promote `cleaned/<dataset>.gpkg` to `reviewed/<dataset>.gpkg`.
8. Update `meta.yaml` with version and reviewer info.
9. If exposed via the API, update `docs/API_SHAPE.md` with the new endpoint.

### When adding a new module

1. Read `docs/CHARTER.md` to confirm scope fit.
2. Module lives at `src/modules/<module>.py`.
3. Module reads data ONLY through the loader.
4. Module returns a `Result` object (TBD — schema to be defined when first module is built).
5. Module declares its compute tier (interactive / on-demand / batch).
6. Validation: results compared against a reference implementation (Ladybug for radiation/comfort, etc.) before declaring the module ready.

## Pointers to other docs

- `${CATALOGUE_PATH}/CLAUDE.md` — catalogue rules, how to add data sources
- `${CATALOGUE_PATH}/SCHEMA.md` — catalogue field reference
- `src/data/SCHEMA.md` — canonical data schema
- `docs/API_SHAPE.md` — backend↔frontend contract
- `docs/FETCH_CHECKLIST.md` — what to ingest, in what order
- `docs/CHARTER.md` — project scope and positioning
- `docs/DATA_CONVENTIONS.md` — pipeline rules for the shared-drive data folder
- `docs/prompts/` — pre-written prompts for specific tasks

## What this repo is NOT

A few clarifications to prevent scope creep:

- Not a strategic regional planning tool (that's Tygron's space).
- Not a specialist simulation tool for defensible absolute numbers (that's Ladybug, EnergyPlus, NoiseModelling, etc.).
- Not a final-verification tool — deep analysis exports to specialist software when needed.
- Not currently multi-tenant. Architecture is compatible with multi-tenancy later, but auth and tenancy are deferred.

If a request is asking for something out of scope, flag it. Don't quietly grow the project.
