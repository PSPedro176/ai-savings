-- =============================================================================
-- model_ref_snapshot — tabela materializada da referência de modelos (CTAS de v_model_ref)
-- =============================================================================
-- O app lê ESTA tabela (via SQL Warehouse), não a view, para o service principal do App
-- não precisar de acesso a system tables. Recriada a cada refresh pelo job `leaderboard`.
-- Herda todas as colunas de v_model_ref, incluindo `match_key` e `on_databricks`.
-- =============================================================================
CREATE OR REPLACE TABLE perdomo_demos_catalog.ai_savings.model_ref_snapshot AS
SELECT * FROM perdomo_demos_catalog.ai_savings.v_model_ref;
