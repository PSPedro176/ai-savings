-- =============================================================================
-- v_aa_model_ref — referência de performance/preço por modelo (Artificial Analysis)
-- =============================================================================
-- Último snapshot (max captured_at) da tabela aa_leaderboard, por modelo, com o que a
-- fase 2 precisa: performance (intelligence) e preços diretos por 1M tokens
-- (input, output, cache-hit=leitura, cache-write=escrita).
--
-- Chave de join com o consumo real: `slug_norm` = slug normalizado igual à
-- v_model_usage_daily (LOWER(REGEXP_REPLACE(x,'[ .]+','-'))) — casa direto com
-- destination_model na maioria dos modelos.
--
-- Só modelos "chat" com performance e preço (intelligence e price_input não nulos) —
-- embeddings e afins caem fora naturalmente.
-- =============================================================================
CREATE OR REPLACE VIEW perdomo_demos_catalog.ai_savings.v_aa_model_ref AS
WITH latest AS (
  SELECT * FROM perdomo_demos_catalog.ai_savings.aa_leaderboard
  WHERE captured_at = (SELECT MAX(captured_at) FROM perdomo_demos_catalog.ai_savings.aa_leaderboard)
)
SELECT
  LOWER(REGEXP_REPLACE(slug, '[ .]+', '-')) AS slug_norm,
  model,
  slug,
  provider,
  intelligence,
  price_input,
  price_output,
  CAST(get_json_object(pricing_json, '$.price_1m_cache_hit_tokens')   AS DOUBLE) AS price_cache_read,
  CAST(get_json_object(pricing_json, '$.price_1m_cache_write_tokens') AS DOUBLE) AS price_cache_write
FROM latest
WHERE intelligence IS NOT NULL
  AND price_input IS NOT NULL
  AND slug IS NOT NULL;
