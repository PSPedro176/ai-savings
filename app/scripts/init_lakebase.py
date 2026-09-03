#!/usr/bin/env python
"""Cria o database `ai_savings` na instância Lakebase e aplica app/db/schema.sql.

Idempotente: pode rodar várias vezes. Usa OAuth do perfil da CLI como senha do
Postgres (token de curta duração). Requer: databricks CLI autenticada no perfil.

Uso:
    uv run --with "psycopg[binary]" app/scripts/init_lakebase.py \
        --project ai-savings --profile perdomo --database ai_savings
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess


def _cli_json(args: list[str]) -> dict | list:
    out = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def connection_params(project: str, branch: str, endpoint: str, profile: str) -> dict:
    base = f"projects/{project}/branches/{branch}"
    endpoints = _cli_json(["databricks", "postgres", "list-endpoints", base,
                           "--profile", profile, "-o", "json"])
    host = endpoints[0]["status"]["hosts"]["host"]
    cred = _cli_json(["databricks", "postgres", "generate-database-credential",
                      f"{base}/endpoints/{endpoint}", "--profile", profile, "-o", "json"])
    me = _cli_json(["databricks", "current-user", "me", "--profile", profile, "-o", "json"])
    return {"host": host, "user": me["userName"], "password": cred["token"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="ai-savings")
    ap.add_argument("--branch", default="production")
    ap.add_argument("--endpoint", default="primary")
    ap.add_argument("--profile", default="perdomo")
    ap.add_argument("--database", default="ai_savings")
    args = ap.parse_args()

    import psycopg  # imported here so the uv --with dep is only needed at runtime

    p = connection_params(args.project, args.branch, args.endpoint, args.profile)
    conn_common = dict(host=p["host"], port=5432, user=p["user"],
                       password=p["password"], sslmode="require")

    # 1) CREATE DATABASE (fora de transação; checa antes pois não há IF NOT EXISTS).
    with psycopg.connect(dbname="postgres", autocommit=True, **conn_common) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (args.database,)
        ).fetchone()
        if exists:
            print(f"database {args.database} já existe")
        else:
            conn.execute(f'CREATE DATABASE "{args.database}"')
            print(f"database {args.database} criado")

    # 2) Aplica o schema no database alvo.
    schema_sql = (pathlib.Path(__file__).resolve().parents[1] / "db" / "schema.sql").read_text()
    with psycopg.connect(dbname=args.database, autocommit=True, **conn_common) as conn:
        conn.execute(schema_sql)
    print("schema aplicado (estimates)")


if __name__ == "__main__":
    main()
