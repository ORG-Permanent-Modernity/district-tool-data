# District Analysis Tool

A web-based design-exploration tool for environmental and energy performance of European urban blocks. Built at ORG Urbanism & Architecture.

## Status

Early development. Currently focused on building the data pipeline (ingest + cleaning + loader) for the first reference neighbourhood in Antwerp.

## Repository structure

```
.
├── CLAUDE.md                 ← persistent rules for Claude Code sessions
├── README.md                 ← this file
├── src/
│   ├── data/                 ← data loader (the contract) + schema doc + catalogue access
│   ├── ingest/               ← per-dataset fetch scripts
│   ├── clean/                ← per-dataset cleaning scripts
│   ├── modules/              ← analysis modules (later)
│   └── api/                  ← FastAPI endpoints (later)
├── docs/
│   ├── CHARTER.md            ← project scope and positioning
│   ├── API_SHAPE.md          ← backend↔frontend contract
│   ├── FETCH_CHECKLIST.md    ← prioritised dataset fetch list
│   ├── DATA_CONVENTIONS.md   ← pipeline rules for the shared-drive data folder
│   └── prompts/              ← task prompts for Claude Code
└── tests/                    ← pytest tests
```

The geo-catalogue lives in its own repo, cloned locally and referenced via the `CATALOGUE_PATH` env var. See setup below.

Data lives on a shared drive, not in this repo. See `CLAUDE.md` for the data root structure.

## Getting started (developer)

### Prerequisites

- Python 3.11 or newer
- Access to the shared drive holding `district-tool-data/`
- Access to the `geo-catalogue` repo
- (Recommended) QGIS for inspecting cleaned data before promotion to `reviewed/`

### Setup

```bash
# 1. Clone this repo
git clone <model-repo-url>
cd district-tool

# 2. Clone the catalogue repo somewhere stable on your machine
git clone git@github.com:ORG/geo-catalogue.git ~/repos/geo-catalogue

# 3. Set environment variables
cp .env.example .env
# Edit .env: set DATA_ROOT (shared drive path) and CATALOGUE_PATH (catalogue clone path)

# 4. Install Python dependencies (using conda)
conda create -n district-tool python=3.11 -y
conda activate district-tool
pip install -e ".[dev]"

# 5. Verify
pytest tests/test_smoke.py
python -c "from src.data.catalogue_access import Catalogue; print(f'{len(Catalogue())} datasets in catalogue')"
```

If the last line prints something like `28 datasets in catalogue`, you're wired up correctly. If it errors, the message will tell you what's wrong with `CATALOGUE_PATH`.

### Running an ingest

The ingest pipeline is documented in `docs/FETCH_CHECKLIST.md`. To kick off an ingest session, paste `docs/prompts/ingest_session.md` into Claude Code.

The general workflow per dataset:

1. **Ingest** — fetches raw data into `district-tool-data/<city>/<neighbourhood>/raw/`
2. **Clean** — automated cleaning into `cleaned/`, with a cleaning log
3. **Human review** — open the cleaned output in QGIS, sanity-check
4. **Promote** — copy `cleaned/<file>` to `reviewed/`, update `meta.yaml`
5. **Done** — the loader can now serve this dataset

## Documentation

- `CLAUDE.md` — rules for working in this repo (read this first if using Claude Code)
- `docs/CHARTER.md` — what the project is, scope, what it is not
- `docs/API_SHAPE.md` — what the backend serves to the frontend
- `src/data/SCHEMA.md` — what the data layer exposes, semantically
- `docs/FETCH_CHECKLIST.md` — the dataset fetch plan
- `docs/DATA_CONVENTIONS.md` — pipeline rules for the shared-drive data folder

## Updating the catalogue

When you need to update the catalogue (add a dataset, fix an endpoint), do it in the catalogue repo:

```bash
cd ~/repos/geo-catalogue
# edit YAML files
git commit -am "Add <dataset>"
git push
```

Then back in the model repo, you don't need to do anything — `python -c "from src.data.catalogue_access import Catalogue; ..."` will pick up the latest from your local clone. To get a colleague's catalogue updates:

```bash
cd ~/repos/geo-catalogue && git pull
```

## Contributing

For ORG team members: branches per feature, PRs to `main`. Code review required for changes touching `src/data/loader.py` (the contract) or the schema.

For Claude Code sessions: read `CLAUDE.md`, work to its conventions, stop and ask when significant decisions arise.

## License

Internal ORG project. Licensing TBD when external collaboration begins.
