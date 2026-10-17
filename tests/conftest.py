"""Setări pentru teste: bază de date temporară, zi demo fixă (luni), istoric scurt ca testele să fie rapide."""
import os
import tempfile

os.environ.setdefault("PORTI_DATA_DIR", tempfile.mkdtemp(prefix="porti_test_"))
os.environ.setdefault("PORTI_ZI_DEMO", "2026-10-19")
os.environ.setdefault("PORTI_ZILE_ISTORIC", "60")
os.environ.setdefault("PORTI_METEO_OFFLINE", "1")

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
