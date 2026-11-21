import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import api
from .config import get_settings
from .db import Base, engine

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="CNC Quote", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(api)


@app.on_event("startup")
def startup():
    # Development convenience; production uses Alembic migrations (alembic upgrade head).
    Base.metadata.create_all(engine())
    _add_missing_columns()
    from .db import SessionLocal
    from .services.shopdata import ensure_reference_materials
    db = SessionLocal()
    try:
        ensure_reference_materials(db)
        db.commit()
    finally:
        db.close()


def _add_missing_columns():
    """create_all() does not add columns to existing tables; add the simple ones introduced since (until Alembic is set up)."""
    from sqlalchemy import inspect, text
    eng = engine()
    insp = inspect(eng)
    with eng.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have and col.server_default is not None:
                    ddl = col.type.compile(dialect=eng.dialect)
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl} NOT NULL DEFAULT {col.server_default.arg}'))


@app.get("/api/health")
def health():
    return {"ok": True}
