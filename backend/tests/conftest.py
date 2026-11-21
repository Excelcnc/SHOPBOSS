import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://cnc:cnc@localhost:5432/cncquote_test")
os.environ["STORAGE_DIR"] = "/tmp/cncquote-test-files"
os.environ["RUN_JOBS_INLINE"] = "true"
os.environ["AUTH_MODE"] = "dev"
os.environ["ANTHROPIC_API_KEY"] = ""
SAMPLES = ROOT.parent / "samples"


@pytest.fixture(scope="session")
def samples():
    return SAMPLES


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.config import get_settings
    from app.db import Base, engine, reset_engine
    import app.models  # noqa: F401  (register every table so drop_all clears them)
    get_settings.cache_clear()
    reset_engine()
    Base.metadata.drop_all(engine())
    from app.main import app
    with TestClient(app) as c:
        c.headers.update({"X-Dev-User": "est@shop.example", "X-Dev-Shop": "Test Shop"})
        yield c
