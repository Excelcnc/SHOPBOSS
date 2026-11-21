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
    from .db import add_missing_columns
    added = add_missing_columns(engine())
    if added:
        logging.getLogger(__name__).info("added database columns: %s", ", ".join(added))
    from .db import SessionLocal
    from .services.shopdata import ensure_reference_materials
    db = SessionLocal()
    try:
        ensure_reference_materials(db)
        db.commit()
    finally:
        db.close()


@app.get("/api/health")
def health():
    return {"ok": True}
