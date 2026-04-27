# Claude Code — First-Time Setup

Paste this prompt the first time you open the repo in Claude Code. It walks through getting the project to a state where ingest can begin.

---

I'm setting up this project for the first time. Walk me through:

## Read first

1. `README.md` — project overview
2. `CLAUDE.md` — repo conventions
3. `docs/CHARTER.md` — what the project is and isn't

## Setup tasks (in order)

### 1. Confirm the catalogue is accessible

The catalogue lives in its own repo, cloned locally and referenced via the `CATALOGUE_PATH` env var. Confirm it's set up:

```bash
python -c "from src.data.catalogue_access import Catalogue; cat = Catalogue(); print(f'{len(cat)} datasets')"
```

If this errors:
- "CATALOGUE_PATH is not set" → I need to add it to `.env`. Show me the template from `.env.example`.
- "CATALOGUE_PATH points at ..., which does not exist" → the path is wrong, or I haven't cloned the catalogue repo yet.
- "does not look like the geo-catalogue repo" → wrong path, pointing at something else.

If it works, also verify the catalogue's own scripts run:

```bash
python "$CATALOGUE_PATH/scripts/validate.py"
python "$CATALOGUE_PATH/scripts/fetch.py" list --region flanders | head
```

### 2. Confirm the Python environment

Check that `pyproject.toml` exists and dependencies install cleanly:

```bash
conda create -n district-tool python=3.11 -y
conda activate district-tool
pip install -e ".[dev]"
```

Run the smoke test:

```bash
pytest tests/test_smoke.py
```

### 3. Confirm the data root

The `.env` file should set `DATA_ROOT`. If it's not set or the path doesn't exist:

```bash
echo "DATA_ROOT=$DATA_ROOT"
ls -la "$DATA_ROOT" 2>/dev/null && echo "OK" || echo "DATA_ROOT not accessible"
```

### 4. Initialise the data folder structure for the first neighbourhood

We're targeting Antwerp first. The first neighbourhood is TBD — I'll tell you which one. Once decided:

- Create `${DATA_ROOT}/antwerp/<neighbourhood>/{raw,cleaned,reviewed}/`
- Create an empty `meta.yaml` at the neighbourhood root using `docs/templates/meta_template.yaml` as a starting point
- Create an empty `_ingest_log.yaml` at `${DATA_ROOT}/antwerp/_ingest_log.yaml` if it doesn't exist
- Copy `docs/DATA_CONVENTIONS.md` to `${DATA_ROOT}/CONVENTIONS.md` if not already there

### 5. Stop and tell me what's left

After steps 1–4, stop. Tell me:

- Catalogue status (accessible via CATALOGUE_PATH and Catalogue() works, or what's missing)
- Python environment status (working / broken)
- Data root status (accessible / not)
- Neighbourhood folder created (yes / no)
- Whether the AOI polygon for the chosen neighbourhood exists at `${DATA_ROOT}/antwerp/<neighbourhood>/aoi.gpkg`

The AOI is the only thing I need to draw manually in QGIS — you can't generate it. If it doesn't exist, tell me and stop. Once I've drawn it and put it in place, I'll come back and we can start the ingest session with `docs/prompts/ingest_session.md`.

## Hard rules

- Don't write any ingest or cleaning scripts in this session. This is setup only.
- Don't commit anything to git yet — I want to review first.
- If a step fails for an unexpected reason, stop and tell me; don't try to work around it.
