"""Test config: force the SQLite backend so the suite needs no Docker/Neo4j.

Env vars are set at import time (before any `store`/`server` import) so the
module-level `Store = ...` selection and `s = Store()` in server.py pick up the
temp sqlite db.
"""

import os
import pathlib
import sys
import tempfile

TESTS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "src"))

os.environ["STORE_BACKEND"] = "sqlite"
_DB = pathlib.Path(tempfile.gettempdir()) / "context_engine_test.db"
for suffix in ("", "-wal", "-shm"):
    p = pathlib.Path(str(_DB) + suffix)
    if p.exists():
        p.unlink()
os.environ["SQLITE_PATH"] = str(_DB)

import pytest  # noqa: E402


@pytest.fixture
def seeded():
    """Wipe and re-ingest the fixture data; return a store on the temp db."""
    import store as store_mod

    s = store_mod.Store()
    s.wipe()
    cwd = os.getcwd()
    os.chdir(TESTS)  # so ingest's `data/...` resolves to tests/data/...
    try:
        import ingest

        ingest.main()
    finally:
        os.chdir(cwd)
    return s
