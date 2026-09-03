"""Carrega a referência de modelo (v_model_ref: AA + disponibilidade Databricks) via
SQL warehouse e cacheia em memória. É a fonte do motor de cálculo e do autocomplete."""
from __future__ import annotations

import threading
import time

from .config import WAREHOUSE_ID, MODEL_REF_VIEW, get_workspace_client

_TTL = 3600.0
_lock = threading.Lock()
_cache: dict = {"rows": None, "ts": 0.0}

_COLS = [
    "slug_norm", "model", "slug", "provider", "intelligence",
    "price_input", "price_output", "price_cache_read", "price_cache_write",
    "blended_price", "tokens_per_s", "match_key", "on_databricks", "databricks_endpoint",
]


def _to_num(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fetch() -> list[dict]:
    w = get_workspace_client()
    # Ordem das colunas é a do SELECT — não dependemos do manifest (pode vir vazio).
    stmt = f"SELECT {', '.join(_COLS)} FROM {MODEL_REF_VIEW}"
    resp = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID, statement=stmt, wait_timeout="50s"
    )
    # Não engolir falhas do statement (permissão, etc.) como resultado vazio.
    status = getattr(resp, "status", None)
    state = getattr(getattr(status, "state", None), "value", None) or str(getattr(status, "state", ""))
    if state and state not in ("SUCCEEDED", "StatementState.SUCCEEDED"):
        err = getattr(status, "error", None)
        raise RuntimeError(f"statement {state}: {getattr(err, 'message', err)}")
    cols = _COLS
    manifest = getattr(resp, "manifest", None)
    if manifest is not None and getattr(manifest, "schema", None) is not None:
        cols = [c.name for c in manifest.schema.columns]
    data = (resp.result.data_array if getattr(resp, "result", None) else None) or []
    num_cols = {"intelligence", "price_input", "price_output", "price_cache_read",
                "price_cache_write", "blended_price", "tokens_per_s"}
    rows = []
    for r in data:
        rec = dict(zip(cols, r))
        for c in num_cols:
            rec[c] = _to_num(rec.get(c))
        rec["on_databricks"] = str(rec.get("on_databricks")).lower() in ("true", "1", "t")
        rows.append(rec)
    return rows


def get_model_ref(force: bool = False) -> list[dict]:
    with _lock:
        now = time.time()
        if force or _cache["rows"] is None or (now - _cache["ts"]) > _TTL:
            _cache["rows"] = _fetch()
            _cache["ts"] = now
        return _cache["rows"]
