import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .api import api
from .routers.accounts import router as accounts_router
from .config import get_settings
from .db import Base, engine

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="CNC Quote", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(accounts_router)
app.include_router(api)


@app.on_event("startup")
def startup():
    # Development and tests create tables directly; deployments run "alembic upgrade head" first (start.sh).
    if get_settings().dev:
        Base.metadata.create_all(engine())
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


# Single-service deployments (Render): serve the built web app from the same server.
_static = get_settings().static_dir
if _static and Path(_static, "index.html").exists():
    app.mount("/assets", StaticFiles(directory=Path(_static, "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        f = Path(_static, path)
        if path and f.is_file() and f.resolve().is_relative_to(Path(_static).resolve()):
            return FileResponse(f)
        return FileResponse(Path(_static, "index.html"), headers={"Cache-Control": "no-cache"})
