"""Pool asyncpg para o Lakebase (Postgres). A senha é uma *database credential* do
Lakebase (JWT específico do endpoint), gerada via REST `POST /api/2.0/postgres/credentials`
— NÃO o token OAuth genérico do workspace. Renovada periodicamente (expira ~1h).
Vale igual no App (service principal) e local (perfil da CLI), pois usa o SDK."""
from __future__ import annotations

import os
import time

import asyncpg

from .config import get_workspace_client

_TOKEN_TTL = 45 * 60  # renova antes de expirar (~1h)

# Endpoint do Lakebase que serve o database (path do tier autoscaling).
_ENDPOINT_PATH = os.environ.get(
    "LAKEBASE_ENDPOINT_PATH",
    "projects/ai-savings/branches/production/endpoints/primary",
)


def _db_credential() -> str:
    """Gera a credencial de database do Lakebase para o endpoint configurado."""
    w = get_workspace_client()
    resp = w.api_client.do(
        "POST", "/api/2.0/postgres/credentials", body={"endpoint": _ENDPOINT_PATH}
    )
    return resp["token"]


class DatabasePool:
    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None
        self._token_ts = 0.0

    async def get_pool(self) -> asyncpg.Pool:
        if not os.environ.get("PGHOST"):
            raise RuntimeError("PGHOST não definido — Lakebase não configurado")
        if self._pool is not None and (time.time() - self._token_ts) < _TOKEN_TTL:
            return self._pool
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
        # No App, PGUSER = service principal (client id) quando não informado explicitamente.
        pguser = os.environ.get("PGUSER") or os.environ.get("DATABRICKS_CLIENT_ID", "")
        self._pool = await asyncpg.create_pool(
            host=os.environ["PGHOST"],
            port=int(os.environ.get("PGPORT", "5432")),
            database=os.environ.get("PGDATABASE", "ai_savings"),
            user=pguser,
            password=_db_credential(),
            ssl="require",
            min_size=1,
            max_size=5,
        )
        self._token_ts = time.time()
        return self._pool


db = DatabasePool()
