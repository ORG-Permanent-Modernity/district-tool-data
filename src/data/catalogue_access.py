"""Access the externally-located geo-catalogue.

The catalogue lives in its own repo, cloned somewhere on the developer's
machine. The path is read from the CATALOGUE_PATH env var (set in .env).

Usage:
    from src.data.catalogue_access import Catalogue
    cat = Catalogue()
    url = cat.endpoint("grb_gebouwen", "wfs")

This module exists so that the import path stays stable even though the
catalogue itself is external. If the catalogue ever becomes a pip-installable
package, only this file changes.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _catalogue_path() -> Path:
    """Resolve the catalogue path from the environment.

    Raises a clear error if CATALOGUE_PATH is not set or the path doesn't
    exist — much better than a confusing ImportError later.
    """
    raw = os.getenv("CATALOGUE_PATH")
    if not raw:
        raise RuntimeError(
            "CATALOGUE_PATH is not set. Add it to your .env file pointing "
            "at your local clone of the geo-catalogue repo. Example:\n"
            "    CATALOGUE_PATH=/Users/yourname/repos/geo-catalogue"
        )
    path = Path(raw).expanduser().resolve()
    if not path.exists():
        raise RuntimeError(
            f"CATALOGUE_PATH points at {path}, which does not exist. "
            "Check the path or run `git pull` in the catalogue repo."
        )
    if not (path / "scripts" / "fetch.py").exists():
        raise RuntimeError(
            f"CATALOGUE_PATH ({path}) does not look like the geo-catalogue "
            "repo — expected to find scripts/fetch.py inside."
        )
    return path


# Make the catalogue importable
_path = _catalogue_path()
if str(_path) not in sys.path:
    sys.path.insert(0, str(_path))

# Re-export Catalogue from the catalogue's fetch module
from scripts.fetch import Catalogue  # noqa: E402

__all__ = ["Catalogue"]
