"""Referência de modelos para a UI: providers suportados e modelos p/ autocomplete."""
from __future__ import annotations

from fastapi import APIRouter

from ..model_ref import get_model_ref
from ..engine import tier_of, TIER_LABELS

router = APIRouter()

# Providers oferecidos no dropdown (modelos atuais do cliente). Por ora, core-providers.
SUPPORTED_PROVIDERS = ["Anthropic", "OpenAI"]


@router.get("/providers")
def providers() -> dict:
    return {"providers": SUPPORTED_PROVIDERS}


@router.get("/models")
def models(provider: str | None = None) -> dict:
    """Modelos (para autocomplete da grade). Filtra por provider quando informado."""
    ref = get_model_ref()
    out = []
    for r in ref:
        if r.get("intelligence") is None:
            continue
        if provider and (r.get("provider") or "").lower() != provider.lower():
            continue
        t = tier_of(r.get("intelligence"))
        out.append({
            "slug": r["slug_norm"],
            "model": r.get("model") or r["slug_norm"],
            "provider": r.get("provider"),
            "intelligence": r.get("intelligence"),
            "tier": t,
            "tier_label": TIER_LABELS[t],
            "on_databricks": r.get("on_databricks", False),
        })
    out.sort(key=lambda m: (m["intelligence"] or 0), reverse=True)
    return {"models": out}
