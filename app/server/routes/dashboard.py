"""Embed do dashboard AI/BI da Fase 1 (aba 'Acompanhar economia')."""
from __future__ import annotations

from fastapi import APIRouter

from ..config import DASHBOARD_ID, get_workspace_client, get_workspace_host

router = APIRouter()

DASHBOARD_NAME = "AI Savings"
_resolved: dict = {"id": None}


def _dashboard_id() -> str | None:
    if DASHBOARD_ID:
        return DASHBOARD_ID
    if _resolved["id"]:
        return _resolved["id"]
    try:
        w = get_workspace_client()
        for d in w.lakeview.list():
            if (d.display_name or "").strip() == DASHBOARD_NAME:
                _resolved["id"] = d.dashboard_id
                return d.dashboard_id
    except Exception:
        return None
    return None


@router.get("/dashboard-embed")
def dashboard_embed() -> dict:
    host = get_workspace_host().rstrip("/")
    did = _dashboard_id()
    return {
        "host": host,
        "dashboard_id": did,
        # AI/BI embed (requer o domínio do app nos approved domains de embedding do workspace)
        "embed_url": f"{host}/embed/dashboardsv3/{did}" if did else None,
        # fallback: abrir no Databricks
        "open_url": f"{host}/dashboardsv3/{did}/published" if did else host,
    }
