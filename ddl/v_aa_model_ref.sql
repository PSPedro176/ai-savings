-- =============================================================================
-- v_aa_model_ref — referência de performance/preço por modelo (Artificial Analysis)
-- =============================================================================
-- Último snapshot (max captured_at) da tabela aa_leaderboard, com o que a fase 2
-- precisa: performance (intelligence) e preços diretos por 1M tokens
-- (input, output, cache-hit=leitura, cache-write=escrita).
--
-- Chave de join com o consumo real: `slug_norm` = slug normalizado igual à
-- v_model_usage_daily (LOWER(REGEXP_REPLACE(x,'[ .]+','-'))) — casa direto com
-- destination_model na maioria dos modelos.
--
-- Só modelos "chat" com performance e preço (intelligence e price_input não nulos) —
-- embeddings e afins caem fora naturalmente.
--
-- COLAPSO DE ESFORÇO/REASONING: a API free da AA lista cada nível de esforço como um
-- "modelo" separado (ex.: "GPT-5.6 Sol (low|medium|high|xhigh|max)"), com MESMO preço
-- por token e só a `intelligence` variando. Como aqui medimos apenas TOKENS (o custo por
-- token independe do esforço), colapsamos para 1 linha por (provider, modelo-base):
--   * modelo-base = nome sem o sufixo entre parênteses;
--   * representante = slug mais curto (o canônico, que casa com o uso real do gateway),
--     desempate pela maior intelligence (melhor esforço);
--   * `model` passa a exibir o nome-base limpo (sem "(max)"/"(high)"...).
-- Schema inalterado. ~418 -> ~286 linhas.
-- =============================================================================
CREATE OR REPLACE VIEW perdomo_demos_catalog.ai_savings.v_aa_model_ref AS
WITH latest AS (
  SELECT * FROM perdomo_demos_catalog.ai_savings.aa_leaderboard
  WHERE captured_at = (SELECT MAX(captured_at) FROM perdomo_demos_catalog.ai_savings.aa_leaderboard)
),
parsed AS (
  SELECT
    LOWER(REGEXP_REPLACE(slug, '[ .]+', '-')) AS slug_norm,
    TRIM(REGEXP_REPLACE(model, '\\s*\\(.*\\)\\s*$', '')) AS base_model,
    slug,
    provider,
    intelligence,
    price_input,
    price_output,
    CAST(get_json_object(pricing_json, '$.price_1m_cache_hit_tokens')   AS DOUBLE) AS price_cache_read,
    CAST(get_json_object(pricing_json, '$.price_1m_cache_write_tokens') AS DOUBLE) AS price_cache_write,
    blended_price,
    tokens_per_s
  FROM latest
  WHERE intelligence IS NOT NULL
    AND price_input IS NOT NULL
    AND slug IS NOT NULL
),
-- 1 representante por (provider, modelo-base): slug canônico (mais curto) primeiro,
-- desempate pela maior intelligence (melhor nível de esforço).
ranked AS (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY provider, base_model
      ORDER BY LENGTH(slug_norm) ASC, intelligence DESC
    ) AS rn
  FROM parsed
)
SELECT
  slug_norm,
  base_model AS model,
  slug,
  provider,
  intelligence,
  price_input,
  price_output,
  price_cache_read,
  price_cache_write,
  blended_price,
  tokens_per_s
FROM ranked
WHERE rn = 1;
