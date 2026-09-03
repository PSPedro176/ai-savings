"""Pool asyncpg para o Lakebase (Postgres). A senha é uma *database credential* do
Lakebase (JWT específico do endpoint), gerada via REST `POST /api/2.0/postgres/credentials`
— NÃO o token OAuth genérico do workspace. Renovada periodicamente (expira ~1h).
Vale igual no App (service principal) e local (perfil da CLI), pois usa o SDK."""
from __future__ import annotations

import os
import pathlib
import time

import asyncpg

from .config import get_workspace_client, get_oauth_token

_TOKEN_TTL = 45 * 60  # renova antes de expirar (~1h)
_SCHEMA_SQL = pathlib.Path(__file__).resolve().parents[1] / "db" / "schema.sql"

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


def _password() -> str:
    """Senha do Postgres: preferir a *database credential* do endpoint; se falhar
    (ex.: endpoint path divergente), cair para o token OAuth do SP (app bindado)."""
    try:
        return _db_credential()
    except Exception as e:
        print(f"database credential falhou, usando OAuth token: {e}")
        return get_oauth_token()


class DatabasePool:
    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None
        self._token_ts = 0.0
        self._schema_ready = False

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
            password=_password(),
            ssl="require",
            min_size=1,
            max_size=5,
        )
        self._token_ts = time.time()
        await self._ensure_schema()
        return self._pool

    async def _ensure_schema(self) -> None:
        """Cria a tabela `estimates` no 1º uso (idempotente). O SP conecta com
        CAN_CONNECT_AND_CREATE e vira dono da tabela → read/write sem grant extra.
        Dispensa o script init_lakebase.py no fluxo de deploy."""
        if self._schema_ready or self._pool is None:
            return
        try:
            sql = _SCHEMA_SQL.read_text()
            async with self._pool.acquire() as conn:
                await conn.execute(sql)  # asyncpg (simple protocol) roda múltiplos statements
            self._schema_ready = True
        except Exception as e:  # não derruba o app; loga e segue
            print(f"init do schema Lakebase falhou (segue mesmo assim): {e}")


db = DatabasePool()
