"""Cálculo da estimativa (preview) e persistência (Lakebase) das estimativas salvas."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import db
from ..engine import compute, default_budget
from ..model_ref import get_model_ref

router = APIRouter()


class ModelRow(BaseModel):
    model: str = ""
    input: float = 0
    output: float = 0
    cache_read: float = 0
    cache_write: float = 0
    spend_usd: float = 0


class TierBudget(BaseModel):
    pct_alvo: float
    pct_optimizable: float = 0.0


class ComputeRequest(BaseModel):
    provider: str = ""
    cache_applies: bool = True
    inputs: list[ModelRow] = Field(default_factory=list)
    budget: dict[str, TierBudget] | None = None


class SaveRequest(ComputeRequest):
    title: str | None = None


def _run(req: ComputeRequest) -> dict:
    ref = get_model_ref()
    inputs = [r.model_dump() for r in req.inputs]
    budget = ({k: v.model_dump() for k, v in req.budget.items()}
              if req.budget is not None else default_budget(inputs, ref, req.cache_applies))
    result = compute(inputs, budget, ref, req.cache_applies)
    # devolve também o orçamento efetivo (default quando o cliente ainda não editou)
    result["budget"] = budget
    return result


@router.post("/estimate")
def estimate(req: ComputeRequest) -> dict:
    return _run(req)


def _title(result: dict) -> str:
    s = result.get("savings", 0.0)
    if s >= 1000:
        return f"Economia potencial US$ {s/1000:.1f}k"
    return f"Economia potencial US$ {s:,.0f}"


@router.post("/estimates")
async def save_estimate(req: SaveRequest) -> dict:
    result = _run(req)
    title = req.title or _title(result)
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO estimates (title, provider, cache_applies, inputs, budget, results)
               VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6::jsonb)
               RETURNING id, created_at""",
            title, req.provider, req.cache_applies,
            json.dumps([r.model_dump() for r in req.inputs]),
            json.dumps(result["budget"]),
            json.dumps(result),
        )
    return {"id": str(row["id"]), "created_at": row["created_at"].isoformat(),
            "title": title, "results": result}


@router.get("/estimates")
async def list_estimates() -> dict:
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, created_at, title, provider,
                      (results->>'savings')::float AS savings,
                      (results->>'savings_pct')::float AS savings_pct,
                      (results->>'baseline_cost')::float AS baseline_cost
               FROM estimates ORDER BY created_at DESC LIMIT 100"""
        )
    return {"estimates": [
        {"id": str(r["id"]), "created_at": r["created_at"].isoformat(), "title": r["title"],
         "provider": r["provider"], "savings": r["savings"], "savings_pct": r["savings_pct"],
         "baseline_cost": r["baseline_cost"]}
        for r in rows
    ]}


@router.get("/estimates/{estimate_id}")
async def get_estimate(estimate_id: str) -> dict:
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT id, created_at, title, provider, cache_applies, inputs, budget, results "
            "FROM estimates WHERE id = $1", estimate_id)
    if r is None:
        raise HTTPException(404, "estimativa não encontrada")
    return {"id": str(r["id"]), "created_at": r["created_at"].isoformat(), "title": r["title"],
            "provider": r["provider"], "cache_applies": r["cache_applies"],
            "inputs": json.loads(r["inputs"]), "budget": json.loads(r["budget"]),
            "results": json.loads(r["results"])}


@router.delete("/estimates/{estimate_id}")
async def delete_estimate(estimate_id: str) -> dict:
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM estimates WHERE id = $1", estimate_id)
    return {"deleted": res.endswith("1")}
