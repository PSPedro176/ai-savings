-- =============================================================================
-- Lakebase (Postgres) — schema do App "AI Savings" (Fase 2)
-- =============================================================================
-- Rodar contra o database `ai_savings` da instância Lakebase (não o `postgres`).
-- Uma única tabela guarda cada estimativa criada no app, com os insumos colados,
-- o orçamento editado pelo cliente e o resultado calculado (tudo em JSONB para
-- versionar a forma sem migrações).
-- A referência AA+disponibilidade vem por SYNCED TABLE (schema separado), não aqui.
-- =============================================================================

CREATE TABLE IF NOT EXISTS estimates (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by    TEXT,                       -- e-mail do usuário do app (quando disponível)
    title         TEXT NOT NULL,              -- título derivado (ex.: "Economia potencial US$ 12.3k")
    provider      TEXT NOT NULL,              -- provider dos modelos atuais (anthropic|openai)
    cache_applies BOOLEAN NOT NULL DEFAULT true,
    inputs        JSONB NOT NULL,             -- linhas coladas: [{model,input,output,cache_read,cache_write,spend_usd}]
    budget        JSONB NOT NULL,             -- por tier: {alta:{pct_alvo,pct_optimizable}, ...}
    results       JSONB NOT NULL              -- baseline/target/savings + modelos escolhidos + séries do gráfico
);

-- Listagem da home ("estimativas anteriores") ordena por mais recente.
CREATE INDEX IF NOT EXISTS idx_estimates_created_at ON estimates (created_at DESC);
