# Catalogue Externalisation — File Replacement

This zip contains updated files to externalise the catalogue (it now lives in its own repo, referenced via `CATALOGUE_PATH` env var).

## What to do

1. **Extract this zip.**

2. **Copy all files into your repo, overwriting existing files.** The folder structure mirrors your repo exactly.

3. **Remove the old catalogue placeholder folder** (it's no longer needed):
   ```bash
   rm -rf catalogue/
   ```

4. **Update your `.env` file** — add the `CATALOGUE_PATH` line:
   ```
   CATALOGUE_PATH=/Users/yourname/repos/geo-catalogue
   ```
   Set the actual path to where you've cloned the geo-catalogue repo.

5. **Verify it works:**
   ```bash
   python -c "from src.data.catalogue_access import Catalogue; print(f'{len(Catalogue())} datasets')"
   ```
   Should print something like `28 datasets`. If it errors, the message will tell you what's wrong.

6. **Commit and push:**
   ```bash
   git add .
   git rm -rf catalogue/
   git commit -m "Externalise catalogue: read from CATALOGUE_PATH env var"
   git push
   ```

## Files in this update

| Path | Purpose |
|------|---------|
| `src/data/catalogue_access.py` | NEW — wrapper that imports Catalogue from the external path |
| `.env.example` | UPDATED — adds `CATALOGUE_PATH` variable |
| `CLAUDE.md` | UPDATED — catalogue is external; cardinal rule 2 rewritten |
| `README.md` | UPDATED — setup adds catalogue cloning step |
| `docs/prompts/first_time_setup.md` | UPDATED — verifies catalogue access via CATALOGUE_PATH |
| `docs/prompts/ingest_session.md` | UPDATED — references `${CATALOGUE_PATH}` for catalogue docs |

## Files NOT changed

These don't need changes for this update — they reference the catalogue indirectly or not at all:

- `src/data/loader.py`
- `src/data/SCHEMA.md`
- `src/ingest/_common.py`
- `src/clean/_common.py`
- `docs/CHARTER.md`
- `docs/API_SHAPE.md`
- `docs/FETCH_CHECKLIST.md`
- `docs/DATA_CONVENTIONS.md`
- `docs/templates/meta_template.yaml`
- `pyproject.toml`
- `.gitignore`
- `tests/test_smoke.py`

You can safely leave them alone.
