"""Entrypoint do App AI Savings: API FastAPI + SPA React (frontend/dist)."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server.routes import dashboard, estimate, reference

app = FastAPI(title="AI Savings")

app.include_router(reference.router, prefix="/api")
app.include_router(estimate.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# --- SPA estática (produção) -------------------------------------------------
_FRONTEND = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(_FRONTEND):
    _assets = os.path.join(_FRONTEND, "assets")
    if os.path.isdir(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "not found"}, status_code=404)
        candidate = os.path.join(_FRONTEND, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_FRONTEND, "index.html"))
