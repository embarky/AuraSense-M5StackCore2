"""Storage factory: picks the backend configured in STORAGE_BACKEND."""

from __future__ import annotations

import logging
from typing import Optional

from storage.base import Storage, normalise_reading

log = logging.getLogger(__name__)

__all__ = ["Storage", "create_storage", "normalise_reading"]


def create_storage(backend: str, sqlite_path: str) -> Optional[Storage]:
    """
    Build the configured storage. Returns None when it cannot be initialised,
    so the API keeps serving live data without persistence.
    """
    try:
        if backend == "bigquery":
            from storage.bigquery import BigQueryStorage
            return BigQueryStorage()
        if backend == "sqlite":
            from storage.sqlite import SQLiteStorage
            return SQLiteStorage(sqlite_path)
        raise ValueError(f"Unknown STORAGE_BACKEND '{backend}' (use 'sqlite' or 'bigquery')")
    except Exception as exc:
        log.warning("Storage '%s' unavailable, running without persistence: %s", backend, exc)
        return None
