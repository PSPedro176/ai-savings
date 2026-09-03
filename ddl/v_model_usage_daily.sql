-- =============================================================================
-- v_model_usage_daily — fato diário de consumo de LLM por modelo (custo + tokens)
-- =============================================================================
-- Fonte única de verdade do dashboard "AI Savings". Une, no grão diário por modelo,
-- o CUSTO REAL (faturado pela Databricks) e as CONTAGENS DE TOKEN por tipo.
--
-- Custo real (mesma lógica validada do dashboard oficial AI Gateway Usage Analytics):
--   * PPT / Databricks-hosted : system.billing.usage (usage_type='TOKEN', endpoint
--     governado) x system.billing.list_prices  ->  DBU x preço ($/DBU).
-- Tokens (input/output/cache) : system.ai_gateway.usage, espelhando os filtros do
--   dashboard oficial (exclui AI_QUERY e MCP_SERVICE).
--
-- PREMISSA: todo consumo é via AI Gateway em modelos HOSPEDADOS na Databricks (PPT).
-- Modelos externos (system.ai_gateway.external_model_spend) ficam FORA de escopo — o
-- ramo em_cost foi removido. destination_type deixa de emitir 'External Model'.
--
-- View agnóstica de workspace (workspace_id é coluna) — o dashboard aplica o filtro.
-- Escopo: apenas consumo cobrado por token; provisioned-throughput e batch ficam fora
-- (não têm $/token). Simulação "modelo único" usa custo efetivo agregado (custo/tokens),
-- calculado nos datasets do dashboard sobre esta view.
-- =============================================================================
CREATE OR REPLACE VIEW perdomo_demos_catalog.ai_savings.v_model_usage_daily AS
WITH prices AS (
  SELECT COALESCE(price_end_time, DATE_ADD(CURRENT_DATE, 1)) AS price_end, *
  FROM system.billing.list_prices
  WHERE currency_code = 'USD' AND usage_unit = 'DBU'
),
-- Pay-per-token (Databricks-hosted foundation models): DBU x preço.
ppt_cost AS (
  SELECT
    u.usage_date AS event_date,
    CAST(u.workspace_id AS STRING) AS workspace_id,
    u.usage_metadata.ai_gateway.endpoint_name AS endpoint_name,
    LOWER(REGEXP_REPLACE(TRIM(u.usage_metadata.ai_gateway.destination_model), '[ ._]+', '-')) AS destination_model,
    'Pay Per Token' AS destination_type,
    CAST(SUM(u.usage_quantity * p.pricing.effective_list.default) AS DECIMAL(38,6)) AS cost_usd
  FROM system.billing.usage u
  LEFT JOIN prices p
    ON u.sku_name = p.sku_name
   AND u.usage_date >= p.price_start_time
   AND u.usage_date <  p.price_end
  WHERE u.billing_origin_product = 'MODEL_SERVING'
    AND u.usage_type = 'TOKEN'
    AND u.usage_metadata.ai_gateway.endpoint_name IS NOT NULL
  GROUP BY 1, 2, 3, 4
),
cost_side AS (
  SELECT * FROM ppt_cost
),
-- Tokens por tipo, do log de requisições do gateway.
token_side AS (
  SELECT
    DATE(event_time) AS event_date,
    CAST(workspace_id AS STRING) AS workspace_id,
    endpoint_name,
    LOWER(REGEXP_REPLACE(TRIM(destination_model), '[ ._]+', '-')) AS destination_model,
    SUM(input_tokens)  AS input_tokens,
    SUM(output_tokens) AS output_tokens,
    SUM(total_tokens)  AS total_tokens,
    SUM(COALESCE(token_details.cache_read_input_tokens, 0))     AS cache_read_input_tokens,
    SUM(COALESCE(token_details.cache_creation_input_tokens, 0)) AS cache_creation_input_tokens,
    COUNT(*) AS request_count
  FROM system.ai_gateway.usage
  WHERE destination_model IS NOT NULL
    AND (invocation_metadata.source != 'AI_QUERY' OR invocation_metadata.source IS NULL)
    AND (service_type != 'MCP_SERVICE' OR service_type IS NULL)
  GROUP BY 1, 2, 3, 4
),
-- Nome do workspace (life-quality: filtrar por nome em vez de ID).
ws AS (
  SELECT CAST(workspace_id AS STRING) AS workspace_id, workspace_name
  FROM system.access.workspaces_latest
)
SELECT
  COALESCE(c.event_date, t.event_date)             AS event_date,
  COALESCE(c.workspace_id, t.workspace_id)         AS workspace_id,
  COALESCE(ws.workspace_name, COALESCE(c.workspace_id, t.workspace_id)) AS workspace_name,
  COALESCE(c.endpoint_name, t.endpoint_name)       AS endpoint_name,
  COALESCE(c.destination_model, t.destination_model) AS destination_model,
  -- chave de reconciliação com a AA (mesma partição estável de v_aa_model_ref)
  concat_ws('-',
    nullif(array_join(filter(split(COALESCE(c.destination_model, t.destination_model), '-'), x -> NOT x rlike '^[0-9]+$'), '-'), ''),
    nullif(array_join(filter(split(COALESCE(c.destination_model, t.destination_model), '-'), x ->     x rlike '^[0-9]+$'), '-'), '')
  ) AS match_key,
  COALESCE(c.destination_type, 'Unknown')          AS destination_type,
  CAST(COALESCE(c.cost_usd, 0) AS DECIMAL(38,6))    AS cost_usd,
  COALESCE(t.input_tokens, 0)                       AS input_tokens,
  COALESCE(t.output_tokens, 0)                      AS output_tokens,
  COALESCE(t.total_tokens, 0)                       AS total_tokens,
  COALESCE(t.cache_read_input_tokens, 0)            AS cache_read_input_tokens,
  COALESCE(t.cache_creation_input_tokens, 0)        AS cache_creation_input_tokens,
  COALESCE(t.request_count, 0)                      AS request_count
FROM cost_side c
FULL OUTER JOIN token_side t
  ON  c.event_date       = t.event_date
  AND c.workspace_id     = t.workspace_id
  AND c.endpoint_name    = t.endpoint_name
  AND c.destination_model = t.destination_model
LEFT JOIN ws
  ON ws.workspace_id = COALESCE(c.workspace_id, t.workspace_id);
