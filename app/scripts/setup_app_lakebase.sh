#!/usr/bin/env bash
# Concede ao service principal do App Databricks acesso ao Lakebase (autoscaling).
# O role Postgres do SP PRECISA ser criado via a API postgres (identity_type=SERVICE_PRINCIPAL,
# auth_method=LAKEBASE_OAUTH_V1) — um `CREATE ROLE` manual NÃO é reconhecido no login federado.
#
# Uso: bash app/scripts/setup_app_lakebase.sh <APP_NAME> <PROFILE>
#   ex.: bash app/scripts/setup_app_lakebase.sh ai-savings-dev perdomo
set -euo pipefail

APP="${1:-ai-savings-dev}"
PROFILE="${2:-perdomo}"
PROJECT="ai-savings"
BRANCH="production"

SP=$(databricks apps get "$APP" --profile "$PROFILE" -o json | python3 -c "import sys,json;print(json.load(sys.stdin)['service_principal_client_id'])")
echo "service principal do app: $SP"

# 1) Role Postgres do SP via API (federação OAuth). role-id deve casar ^[a-z][a-z0-9-]*.
databricks postgres create-role "projects/$PROJECT/branches/$BRANCH" \
  --role-id "app-$PROJECT" \
  --json "{\"spec\": {\"identity_type\": \"SERVICE_PRINCIPAL\", \"postgres_role\": \"$SP\", \"auth_method\": \"LAKEBASE_OAUTH_V1\"}}" \
  --profile "$PROFILE" || echo "(role possivelmente já existe — ok)"

# 2) Grants na tabela estimates (least privilege) — via psycopg com credencial do seu perfil.
uv run --with "psycopg[binary]" "$(dirname "$0")/grant_app_sp.py" --client-id "$SP" --profile "$PROFILE"

echo "pronto: SP $SP pode conectar no Lakebase e ler/gravar estimates."
