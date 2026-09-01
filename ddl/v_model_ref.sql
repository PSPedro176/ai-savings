-- =============================================================================
-- v_model_ref — referência de modelo (AA) enriquecida com disponibilidade Databricks
-- =============================================================================
-- Fonte única do MOTOR DE CÁLCULO do app (Fase 2). Estende v_aa_model_ref (performance
-- + preços diretos AA por 1M tokens) com a informação de quais modelos estão servíveis
-- no workspace via Model Serving / AI Gateway.
--
-- Disponibilidade: system.serving.served_entities (endpoints de chat ativos). O nome do
-- endpoint databricks-* casa com o slug AA depois de remover o prefixo `databricks-` e
-- aplicar a MESMA normalização de slug das outras views (LOWER + REGEXP '[ .]+' -> '-').
--
-- Colunas extras:
--   on_databricks       BOOLEAN  — modelo tem endpoint de chat ativo no workspace
--   databricks_endpoint STRING   — nome do endpoint (ex.: databricks-glm-5-3-flash)
--
-- Uso no motor: classificação por `intelligence`, repreço por preços AA, e — para a fatia
-- "passível de otimização" — candidatos mais baratos de performance equivalente FILTRANDO
-- on_databricks = true (premissa: mira em core-providers servidos pela Databricks).
-- =============================================================================
CREATE OR REPLACE VIEW perdomo_demos_catalog.ai_savings.v_model_ref AS
WITH dbx AS (
  SELECT
    LOWER(REGEXP_REPLACE(REGEXP_REPLACE(endpoint_name, '^databricks-', ''), '[ .]+', '-')) AS slug_norm,
    MAX(endpoint_name) AS databricks_endpoint
  FROM system.serving.served_entities
  WHERE task = 'llm/v1/chat'
    AND endpoint_delete_time IS NULL
  GROUP BY 1
)
SELECT
  a.*,
  (d.slug_norm IS NOT NULL) AS on_databricks,
  d.databricks_endpoint
FROM perdomo_demos_catalog.ai_savings.v_aa_model_ref a
LEFT JOIN dbx d USING (slug_norm);
