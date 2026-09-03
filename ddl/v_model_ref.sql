-- =============================================================================
-- v_model_ref — referência de modelo (AA) enriquecida com disponibilidade Databricks
-- =============================================================================
-- Fonte única do MOTOR DE CÁLCULO do app (Fase 2) e do de-para do dashboard. Estende
-- v_aa_model_ref (performance + preços diretos AA por 1M tokens) com a informação de
-- quais modelos estão servíveis no workspace via Model Serving / AI Gateway.
--
-- Disponibilidade: system.serving.served_entities (endpoints de chat ativos). O nome do
-- endpoint databricks-* casa com a AA por `match_key` (a MESMA partição estável de
-- v_aa_model_ref, aplicada ao endpoint sem o prefixo `databricks-`). Isso recupera
-- divergências de ORDEM (ex.: endpoint `databricks-claude-sonnet-4-5` <-> AA
-- `claude-4-5-sonnet`) que o join por slug perdia — antes ~31% dos endpoints servidos
-- ficavam marcados como indisponíveis por engano.
--
-- Colunas extras:
--   match_key           STRING   — chave de reconciliação AA <-> Databricks (herdada de a)
--   on_databricks       BOOLEAN  — modelo tem endpoint de chat ativo no workspace
--   databricks_endpoint STRING   — nome do endpoint (ex.: databricks-claude-sonnet-4-5)
--
-- Uso: TODA sugestão/simulação (app e dashboard) filtra on_databricks = true — nunca
-- oferecer um modelo que não servimos. Modelos servidos sem par na AA (sem preço/
-- performance) não entram aqui; ficam visíveis no relatório de cobertura do dashboard.
-- =============================================================================
CREATE OR REPLACE VIEW perdomo_demos_catalog.ai_savings.v_model_ref AS
WITH dbx AS (
  SELECT
    concat_ws('-',
      nullif(array_join(filter(split(k, '-'), t -> NOT t rlike '^[0-9]+$'), '-'), ''),
      nullif(array_join(filter(split(k, '-'), t ->     t rlike '^[0-9]+$'), '-'), '')
    ) AS match_key,
    MAX(endpoint_name) AS databricks_endpoint
  FROM (
    SELECT
      endpoint_name,
      LOWER(REGEXP_REPLACE(TRIM(REGEXP_REPLACE(endpoint_name, '^databricks-', '')), '[ ._]+', '-')) AS k
    FROM system.serving.served_entities
    WHERE task = 'llm/v1/chat'
      AND endpoint_delete_time IS NULL
  )
  GROUP BY 1
)
SELECT
  a.*,
  (d.match_key IS NOT NULL) AS on_databricks,
  d.databricks_endpoint
FROM perdomo_demos_catalog.ai_savings.v_aa_model_ref a
LEFT JOIN dbx d ON a.match_key = d.match_key;
