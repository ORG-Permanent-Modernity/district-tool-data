# Claude Code — Antwerp Data Ingest Session

Paste this entire prompt into Claude Code when starting an ingest session.

---

I want to work through `docs/FETCH_CHECKLIST.md` and produce ingested + cleaned data for the chosen Antwerp neighbourhood.

## Read first (in order)

1. `CLAUDE.md` — repo conventions and cardinal rules
2. `${CATALOGUE_PATH}/CLAUDE.md` — how to use the catalogue (the catalogue is in its own repo)
3. `src/data/SCHEMA.md` — the canonical data schema
4. `src/data/loader.py` — the loader contract you're feeding into
5. `docs/DATA_CONVENTIONS.md` — raw/cleaned/reviewed pipeline rules
6. `docs/FETCH_CHECKLIST.md` — the ordered fetch list

## Working principles for this session

**One dataset at a time.** Do not start the next dataset until the current one is fully ingested and cleaned.

**Stop after each dataset.** When you've finished cleaning a dataset, write a summary message and stop. I'll review the cleaned data in QGIS and either promote it to `reviewed/` myself or come back with corrections. Only continue when I tell you to.

**Use the catalogue, not hardcoded URLs.** Every fetch goes through:

```python
from src.data.catalogue_access import Catalogue
cat = Catalogue()
url = cat.endpoint("grb_gebouwen", "wfs")
```

The catalogue is in its own repo, accessed via `CATALOGUE_PATH`. If a URL is missing from the catalogue, update the YAML in the catalogue repo (`${CATALOGUE_PATH}`) and `git pull` here — don't paper over it inline.

**Decisions documented in code.** Every cleaning script's docstring lists the decisions made (area thresholds, null-handling, normalisation rules). If a decision feels significant, ask me before committing.

**No silent data drops.** Every cleaning script outputs a `CleaningLog` (see `src/clean/_common.py`) saved alongside the cleaned data. Rows in, rows out, rows dropped (with reasons), columns added, anomalies.

## Per-dataset workflow

1. **Confirm the catalogue entry** exists and the endpoint resolves. If not, stop and tell me.
2. **Write the ingest script** at `src/ingest/<dataset>.py`. Reads catalogue endpoint, fetches, writes to `raw/<dataset>_<YYYY-MM-DD>.gpkg` (or `.tif`). Appends to `_ingest_log.yaml`. Idempotent.
3. **Write the cleaning script** at `src/clean/<dataset>.py`. Reads from `raw/`, writes to `cleaned/`. Saves a `cleaning_log.yaml` alongside. Schema must match what `loader.py` expects.
4. **Run both scripts.** Verify outputs land in `raw/` and `cleaned/`.
5. **Stop and report.** Tell me:
   - What was fetched (rows, file size)
   - What cleaning decisions were applied
   - Any anomalies (null counts, dropped features with reasons)
   - The path to the cleaned file for me to inspect
6. **Wait for me** to either promote to `reviewed/` myself or come back with corrections.

## Hard rules

- **No data in git.** Data lives in `district-tool-data/` on the shared drive (path from `DATA_ROOT` env var).
- **Do not modify the loader contract.** `src/data/loader.py` is the contract. If a cleaning script can't produce data matching the schema, the cleaning script is wrong.
- **EPSG:31370 always.** Reproject during ingest if needed. Reviewed outputs must be 31370.
- **Buffer on fetch, clip strict on reviewed.** See `FETCH_CHECKLIST.md` for per-dataset buffer values.
- **Catalogue edits go in the catalogue repo, not here.** If endpoints need updating, edit the catalogue's YAML files at `${CATALOGUE_PATH}`, push there, and `git pull` to get them locally.

## Order of work

Follow the checklist tier order strictly:

**Session 1 — Tier 1 only (foundations):**
- Step 0: confirm AOI exists at `${DATA_ROOT}/antwerp/<neighbourhood>/aoi.gpkg`. If not, stop and ask.
- Step 1: DHM-II DTM
- Step 2: DHM-II DSM
- Step 3: nDSM (computed)
- Step 4: GRB buildings
- Step 5: GRB 3D supplement (if coverage exists)

After Tier 1, **stop and wait** before Tier 2.

## When something is unclear

- Catalogue missing info: update the catalogue YAML in the catalogue repo, push, pull here. Don't hardcode in the model repo.
- Cleaning decision feels significant: pause and ask.
- Fetch fails: debug, don't retry blindly. WFS endpoints have rate limits and pagination quirks.
- Format unexpected: update the checklist and tell me, don't silently work around.

## Final note

This is data preparation for a tool intended to become a real service. Discipline matters more than speed. Cleaning logs, decision documentation, schema conformance, and catalogue-driven fetching make this work survive review, audit, and migration.

Start with confirming the AOI, then proceed with Tier 1. Stop after each dataset.
