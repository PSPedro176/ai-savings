-- =============================================================================
-- v_aa_model_ref — referência de performance/preço por modelo (Artificial Analysis)
-- =============================================================================
-- Último snapshot (max captured_at) da tabela aa_leaderboard, com o que a fase 2
-- precisa: performance (intelligence) e preços diretos por 1M tokens
-- (input, output, cache-hit=leitura, cache-write=escrita).
--
-- CHAVE DE JOIN = `match_key` (partição estável): normaliza o slug (LOWER + TRIM +
-- '[ ._]+' -> '-'), quebra em tokens e reagrupa LETRAS (na ordem) ++ NÚMEROS (na
-- ordem). Isso reconcilia a divergência de ORDEM entre a AA e a Databricks
-- (ex.: AA `claude-4-5-sonnet` vs Databricks `claude-sonnet-4-5`) SEM colidir
-- inversões de versão (`4-5` != `5-4`, pois a ordem dos números é preservada) e
-- SEM nenhum mapeamento manual. `slug_norm` continua como identidade/display.
--
-- Só modelos "chat" com performance e preço (intelligence e price_input não nulos) —
-- embeddings e afins caem fora naturalmente.
--
-- COLAPSO DE ESFORÇO/REASONING: a API free da AA lista cada nível de esforço como um
-- "modelo" separado (ex.: "GPT-5.6 Sol (low|medium|high|xhigh)"), com MESMO preço
-- por token e só a `intelligence` variando. Como aqui medimos apenas TOKENS (o custo por
-- token independe do esforço), colapsamos para 1 linha por (provider, modelo-base):
--   * modelo-base = nome sem o sufixo entre parênteses;
--   * representante = slug mais curto (o canônico, que casa com o uso real do gateway);
--   * `intelligence` = **MAX** entre as variantes de esforço da base (capacidade do
--     modelo no seu melhor esforço) — antes herdava a do slug curto, que podia ser a
--     variante fraca (ex.: Claude Sonnet 4.6 pegava 36.8 em vez de 48.4).
--   * `model` exibe o nome-base limpo (sem "(max)"/"(high)"...).
-- =============================================================================
CREATE OR REPLACE VIEW perdomo_demos_catalog.ai_savings.v_aa_model_ref AS
WITH latest AS (
  SELECT * FROM perdomo_demos_catalog.ai_savings.aa_leaderboard
  WHERE captured_at = (SELECT MAX(captured_at) FROM perdomo_demos_catalog.ai_savings.aa_leaderboard)
),
parsed AS (
  SELECT
    LOWER(REGEXP_REPLACE(TRIM(slug), '[ ._]+', '-')) AS slug_norm,
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
-- 1 representante por (provider, modelo-base): slug canônico (mais curto) para casar com
-- o uso real; intelligence = MAX entre as variantes de esforço.
ranked AS (
  SELECT *,
    MAX(intelligence) OVER (PARTITION BY provider, base_model) AS max_intel,
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
  max_intel AS intelligence,
  price_input,
  price_output,
  price_cache_read,
  price_cache_write,
  blended_price,
  tokens_per_s,
  -- partição estável: letras (na ordem) ++ números (na ordem)
  concat_ws('-',
    nullif(array_join(filter(split(slug_norm, '-'), t -> NOT t rlike '^[0-9]+$'), '-'), ''),
    nullif(array_join(filter(split(slug_norm, '-'), t ->     t rlike '^[0-9]+$'), '-'), '')
  ) AS match_key
FROM ranked
WHERE rn = 1;
