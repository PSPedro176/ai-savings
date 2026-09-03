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

# O database `ai_savings` é dono do role `app_owner` (lakebase.yml); o app conecta como o
# SP (outro role). No PG15+ o schema `public` não dá CREATE a outros roles, então o SP cria
# um schema PRÓPRIO (tem CREATE no database via CAN_CONNECT_AND_CREATE) e a tabela mora nele.
# O search_path do pool aponta pra cá, então as queries das rotas seguem usando `estimates`.
_APP_SCHEMA = "app_data"

def _norm_endpoint(p: str) -> str:
    """Normaliza o path do endpoint. O binding `lakebase` (valueFrom) entrega o resource
    path; se vier só a branch (sem /endpoints/), assume o endpoint `primary` dela."""
    p = (p or "").strip().strip("/")
    if p and "/endpoints/" not in p:
        p = f"{p}/endpoints/primary"
    return p


# Endpoint do Lakebase que serve o database. Vem do binding do app
# (LAKEBASE_ENDPOINT_PATH = valueFrom: lakebase → projects/<proj>/branches/<target>/endpoints/primary).
_ENDPOINT_PATH = _norm_endpoint(
    os.environ.get(
        "LAKEBASE_ENDPOINT_PATH",
        "projects/ai-savings/branches/dev/endpoints/primary",
    )
)


def _db_credential() -> str:
    """Gera a credencial de database do Lakebase para o endpoint configurado."""
    w = get_workspace_client()
    resp = w.api_client.do(
        "POST", "/api/2.0/postgres/credentials", body={"endpoint": _ENDPOINT_PATH}
    )
    return resp["token"]


def _endpoint_host() -> str:
    """Host do Postgres. No autoscaling o binding NÃO decompõe host/port (valueFrom entrega
    o resource path), então resolvemos o host via GET /api/2.0/postgres/<endpoint_path>.
    Se PGHOST vier como hostname real (sem '/'), usa direto."""
    h = os.environ.get("PGHOST", "")
    if h and "/" not in h:
        return h
    w = get_workspace_client()
    resp = w.api_client.do("GET", f"/api/2.0/postgres/{_ENDPOINT_PATH}")
    hosts = ((resp or {}).get("status") or {}).get("hosts") or {}
    if isinstance(hosts, list):
        hosts = hosts[0] if hosts else {}
    host = hosts.get("host")
    if not host:
        raise RuntimeError(f"host do endpoint {_ENDPOINT_PATH} não resolvido: {resp}")
    return host


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
        if not _ENDPOINT_PATH and not os.environ.get("PGHOST"):
            raise RuntimeError("Lakebase não configurado — LAKEBASE_ENDPOINT_PATH ausente")
        # (Re)cria o pool na 1ª vez ou quando a credencial está para expirar.
        if self._pool is None or (time.time() - self._token_ts) >= _TOKEN_TTL:
            if self._pool is not None:
                await self._pool.close()
                self._pool = None
            # No App, PGUSER = service principal (client id) quando não informado explicitamente.
            # Ignora PGUSER se vier como resource path (com '/') em vez de um usuário real.
            pguser = os.environ.get("PGUSER", "")
            if not pguser or "/" in pguser:
                pguser = os.environ.get("DATABRICKS_CLIENT_ID", "")
            self._pool = await asyncpg.create_pool(
                host=_endpoint_host(),
                port=5432,  # Lakebase Postgres é sempre 5432 (binding não injeta porta decomposta)
                database=os.environ.get("PGDATABASE", "ai_savings"),
                user=pguser,
                password=_password(),
                ssl="require",
                min_size=1,
                max_size=5,
                # Toda conexão enxerga o schema próprio do app primeiro (ver _APP_SCHEMA).
                server_settings={"search_path": f"{_APP_SCHEMA},public"},
            )
            self._token_ts = time.time()
        # Roda em toda chamada, mas retorna cedo quando já pronto; se a criação falhou antes
        # (_schema_ready == False), tenta de novo em vez de mascarar com "relation does not exist".
        await self._ensure_schema()
        return self._pool

    async def _ensure_schema(self) -> None:
        """Cria o schema próprio do app + a tabela `estimates` (idempotente). O SP tem CREATE
        no database (CAN_CONNECT_AND_CREATE) e vira dono do schema/tabela → read/write sem grant.
        Falha ALTO (propaga): só as rotas /estimates dependem disto; o resto do app segue de pé,
        e o /logz mostra a causa real em vez do downstream UndefinedTableError."""
        if self._schema_ready or self._pool is None:
            return
        ddl = _SCHEMA_SQL.read_text()
        async with self._pool.acquire() as conn:
            await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {_APP_SCHEMA}")
            await conn.execute(ddl)  # search_path já aponta pro schema próprio
        self._schema_ready = True


db = DatabasePool()
