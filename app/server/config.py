"""Autenticação dual-mode: dentro do Databricks App (service principal auto-injetado)
ou local (perfil da CLI). Padrão da skill databricks-apps."""
from __future__ import annotations

import os

from databricks.sdk import WorkspaceClient

IS_DATABRICKS_APP = bool(os.environ.get("DATABRICKS_APP_NAME"))
DEFAULT_PROFILE = os.environ.get("DATABRICKS_PROFILE", "perdomo")

_client: WorkspaceClient | None = None


def get_workspace_client() -> WorkspaceClient:
    global _client
    if _client is None:
        _client = WorkspaceClient() if IS_DATABRICKS_APP else WorkspaceClient(profile=DEFAULT_PROFILE)
    return _client


def get_oauth_token() -> str:
    """Token OAuth do workspace (usado como senha do Lakebase no App)."""
    w = get_workspace_client()
    headers = w.config.authenticate()
    if headers and "Authorization" in headers:
        return headers["Authorization"].replace("Bearer ", "")
    return w.config.token  # fallback (PAT)


def get_workspace_host() -> str:
    if IS_DATABRICKS_APP:
        host = os.environ.get("DATABRICKS_HOST", "")
        if host and not host.startswith("http"):
            host = f"https://{host}"
        return host
    return get_workspace_client().config.host


# Configuração do domínio de dados (fully-qualified, igual à Fase 1).
WAREHOUSE_ID = os.environ.get("WAREHOUSE_ID", "8edbc02ddff2de2d")
# Tabela materializada (CTAS de v_model_ref) — o app lê a TABELA, não a view, para não
# exigir que o service principal tenha acesso a system tables.
MODEL_REF_VIEW = os.environ.get(
    "MODEL_REF_VIEW", "perdomo_demos_catalog.ai_savings.model_ref_snapshot"
)
DASHBOARD_ID = os.environ.get("DASHBOARD_ID", "")  # id do dashboard publicado da Fase 1
