"""
Dashboard tests run against a real SQLite file written with the backend's own
storage code, filled by the simulator, so the three parts are tested together.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for sub in ("dashboard", "simulator"):
    sys.path.insert(0, str(ROOT / sub))
os.environ["DATA_SOURCE"] = "sqlite"


def _load_backend_storage():
    """Import backend/storage without putting backend/ on sys.path (its app.py would shadow ours)."""
    import importlib.util
    pkg_dir = ROOT / "backend" / "storage"
    spec = importlib.util.spec_from_file_location("storage", pkg_dir / "__init__.py",
                                                  submodule_search_locations=[str(pkg_dir)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["storage"] = module
    spec.loader.exec_module(module)
    from storage.sqlite import SQLiteStorage
    return module.normalise_reading, SQLiteStorage


@pytest.fixture(scope="session")
def sim_db(tmp_path_factory):
    """Seven days of simulated readings at 1-minute resolution."""
    import aurasense_sim as sim

    normalise_reading, SQLiteStorage = _load_backend_storage()
    path = tmp_path_factory.mktemp("db") / "aurasense.db"
    store = SQLiteStorage(str(path))
    end = datetime.now(timezone.utc)
    rows = [normalise_reading({**r, "location": "Lausanne, CH", "timezone": "Europe/Zurich"}, ts)
            for ts, r in sim.generate(end - timedelta(days=7), end, 60, sim.Room(seed=7), "mixed", 7)]
    store.insert_readings(rows)
    return path


@pytest.fixture
def source(sim_db, monkeypatch):
    import sqlite_source
    monkeypatch.setattr(sqlite_source, "SQLITE_PATH", str(sim_db))
    return sqlite_source
