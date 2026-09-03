#!/usr/bin/env python
"""Concede ao service principal do app acesso ao database ai_savings no Lakebase.

O app autentica no Postgres via OAuth como o service principal — logo precisa de um
ROLE Postgres com nome = client_id do SP, com LOGIN e privilégios na tabela estimates.

Uso:
    uv run --with "psycopg[binary]" app/scripts/grant_app_sp.py \
        --client-id <SP_CLIENT_ID> --profile perdomo
"""
from __future__ import annotations

import argparse

from init_lakebase import connection_params  # reutiliza o helper de conexão


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-id", required=True, help="service_principal_client_id do app")
    ap.add_argument("--project", default="ai-savings")
    ap.add_argument("--branch", default="production")
    ap.add_argument("--endpoint", default="primary")
    ap.add_argument("--profile", default="perdomo")
    ap.add_argument("--database", default="ai_savings")
    args = ap.parse_args()

    import psycopg

    p = connection_params(args.project, args.branch, args.endpoint, args.profile)
    common = dict(host=p["host"], port=5432, user=p["user"], password=p["password"], sslmode="require")
    sp = args.client_id

    with psycopg.connect(dbname=args.database, autocommit=True, **common) as conn:
        # cria o role do SP com LOGIN (o token OAuth do SP mapeia para um role de mesmo nome)
        conn.execute(
            "DO $$ BEGIN "
            f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{sp}') THEN "
            f"CREATE ROLE \"{sp}\" WITH LOGIN; "
            "END IF; END $$;"
        )
        conn.execute(f'GRANT CONNECT ON DATABASE "{args.database}" TO "{sp}"')
        conn.execute(f'GRANT USAGE ON SCHEMA public TO "{sp}"')
        conn.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{sp}"')
        conn.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{sp}"')
    print(f"grants aplicados ao service principal {sp} em {args.database}")


if __name__ == "__main__":
    main()
