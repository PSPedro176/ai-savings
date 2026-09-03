# ai-savings — estado do projeto

Ferramenta para estimar **economia potencial em IA** de clientes Databricks. Duas entregas:
(1) dashboard AI/BI (Lakeview) sobre system tables — Fase 1; (2) **App Databricks** (calculadora
de economia, React+FastAPI) que o cliente usa em self-service com o consumo que ELE traz — Fase 2.

## Ambiente

- **Profile**: `perdomo` (workspace `fevm-perdomo-demos`, `workspace_id=7474649498576628`).
- **Catálogo/schema**: `perdomo_demos_catalog.ai_savings` (hardcoded nas views e no dashboard).
- **Warehouse**: `8edbc02ddff2de2d` (Serverless Starter). Var `warehouse_id` no `databricks.yml`.
- **Secret** da API Artificial Analysis: scope `ai_savings`, key `aa_api_key`.
- System tables aqui são **account-level** (centenas de workspaces) → sempre filtrar por workspace.

## Camada de dados reutilizável (2 views em `ddl/`)

**`v_model_usage_daily`** — fato diário, grão `(event_date, workspace_id, workspace_name,
endpoint_name, destination_model, destination_type)`:
- `cost_usd` = **custo real faturado pela Databricks**. PPT: `system.billing.usage`
  (`usage_type='TOKEN'`) × `system.billing.list_prices` (**$0,07/DBU plano** — billing NÃO
  tem preço por tipo de token). External: `system.ai_gateway.external_model_spend` (já em USD).
- Tokens de `system.ai_gateway.usage`: `input_tokens, output_tokens, total_tokens,
  cache_read_input_tokens, cache_creation_input_tokens`, `request_count`.
- `workspace_name` via `LEFT JOIN system.access.workspaces_latest` (fallback p/ o id).
- Cost side ⨝ token side por `FULL OUTER JOIN` nos 4 campos-chave.

**`v_aa_model_ref`** — último snapshot (`max captured_at`) do leaderboard Artificial Analysis
(tabela `aa_leaderboard`, populada pelo notebook `aa_leaderboard.py`). Colunas:
`slug_norm` (**chave de join** = slug normalizado, casa com `destination_model`), `model`,
`slug`, `provider`, `intelligence`, `price_input`, `price_output`, `price_cache_read`,
`price_cache_write`, `blended_price`, `tokens_per_s`.

## Lógica de cálculo (reutilizar no app)

Relações de token verificadas: `total_tokens = input_tokens + output_tokens`; **`cache_read`
e `cache_write` estão DENTRO de `input_tokens`** → `input_puro = input - cache_read - cache_write`.

- **Modelo único** (mesma régua de faturamento Databricks): `taxa[m] = SUM(cost_usd) /
  SUM(total_tokens)` sobre todo o histórico do workspace; `custo_estimado = tokens_do_período
  × taxa[m]`. `economia = estimado − real` (positivo = mix atual mais barato).
- **Provider/modelo direto** (régua = preço de lista AA): junta `destination_model → v_aa_model_ref`
  por `slug_norm`; **de-para** = modelo do provider-alvo com `intelligence` mais próxima
  (empate p/ cima). Reprecifica: `input_puro×price_input + cache_read×price_cache_read +
  cache_write×price_cache_write + output×price_output`, tudo `/1e6` (fallback dos cache p/
  `price_input` quando nulo). Baseline "real" nesse modo = mix a preço direto AA.
- **Harness** (Claude Code, Codex, OpenCode, Cursor, Gemini CLI, Copilot): derivado de
  `user_agent`/`url` em `ai_gateway.usage`; custo rateado por participação de tokens.

## Armadilhas (importantes para reutilizar a lógica)

- **Precisão**: `DECIMAL/BIGINT` no Spark **trunca** a divisão (colapsa taxas distintas).
  SEMPRE `CAST(SUM(cost_usd) AS DOUBLE)` antes de dividir por tokens.
- **Match com AA é por `slug` normalizado.** Não casam: embeddings, variantes com sufixo de
  data, alguns nomes divergentes → ficam de fora das visões por provider (base justa, mesma
  exclusão em todos os cenários).
- AA (endpoint free) **entrega preço de cache** em `pricing_json`
  (`price_1m_cache_hit_tokens` = leitura, `price_1m_cache_write_tokens` = escrita), apesar de
  a doc pública não listar.

## Dashboard (`ai_savings.lvdash.json`)

4 páginas: **Filtros** (globais: período, workspace por **nome**, modelos usados) · **Provider
único** · **Modelo único** · **Consumo**. As duas abas de comparação têm mesma estrutura:
multi-select do que comparar + single-select do alvo dos cards/linha; 3 cards
(economia/real/comparado); barras totais do período; combo diário (barras = real por modelo,
**linha única** = alvo). Consumo: harness, custo/tokens diários por modelo, tabela AA (com
filtros). Toda a lógica vive nos **datasets do dashboard** (não em views extras).

Wording: usar **"comparar/comparação"**, não "simular/simulação".

## Deploy (DABs)

- **dev** (`mode: development`, prefixo `[dev pedro_perdomo]`, root em `/Users/...`).
- **prod** (`mode: production`, **nome limpo**, root e dashboard em `/Workspace/Shared`).
- `databricks bundle deploy --target <dev|prod> --profile perdomo` (+ `lakeview publish`).
  O guard de dashboard publicado costuma exigir `--force` no redeploy.
- **Job `leaderboard`** centraliza o setup: coleta a AA → condition task `views_missing`
  (task value `create_needed` setado por `aa_leaderboard.py`) → cria as 2 views EM PARALELO
  só se faltarem. Fluxo: deploy → roda o job 1x → tudo pronto; depois roda semanal só coletando.

## App calculadora (Fase 2, `app/`) — React + FastAPI, um serviço

Deploy dev no ar: `https://ai-savings-dev-7474652474621326.aws.databricksapps.com`.
Duas abas: **Estimar economia** (o fluxo) e **Acompanhar economia** (embed do dashboard da Fase 1).

- **Backend** (`app/server/`): `engine.py` = motor de cálculo puro (testado em `app/tests/`);
  `model_ref.py` lê a referência de modelos via warehouse; `db.py` conecta ao Lakebase;
  rotas em `routes/` (reference, estimate, dashboard). `config.py` faz auth dual-mode
  (WorkspaceClient no App / profile `perdomo` local).
- **Frontend** (`app/frontend/`, Vite+React+TS): identidade Databricks tema claro (ver
  `.impeccable.md`). Fluxo em 3 passos: provider → grade colável de consumo → orçamento
  (tiers Alta/Média/Baixa) + gráfico comparativo (2 colunas de tokens/US$, fitas ligando tiers,
  segmentos otimizados em Lava, toggle, título dinâmico). Build em `frontend/dist` (servido
  pelo FastAPI). Sem LLM — a sugestão OSS é lookup determinístico.

### Motor de cálculo (semântica confirmada — o coração do app)
- Distribuição em **tokens**; ambas as colunas a **preço de lista AA** (isola o efeito do
  rebalanceamento + otimização). Gasto US$ digitado = só âncora.
- 4 campos de token **independentes e aditivos** (faturamento Anthropic/OpenAI), ≠ da Fase 1.
- Tier por bandas de `intelligence` (Alta ≥50, Média 28–50, Baixa <28 — em `engine.py`).
- **% alvo** = rebalancear tokens entre tiers (fatia não-otimizada fica nos modelos do cliente);
  **% otimizável** = trocar por modelo equivalente mais barato **disponível na Databricks**.

### Camada de dados nova
- **`ddl/v_model_ref.sql`**: `v_aa_model_ref` + disponibilidade Databricks (`on_databricks`,
  via `system.serving.served_entities`, endpoints `databricks-*` chat ativos; casa por slug).
- **`perdomo_demos_catalog.ai_savings.model_ref_snapshot`**: CTAS de `v_model_ref` (o app lê a
  TABELA, não a view, para o SP não precisar de acesso a system tables). Job recria no refresh.
- **Lakebase** (autoscaling, project `ai-savings`, branch por target, db `ai_savings`): tabela
  `estimates` (JSONB). Declarado no bundle (`resources/lakebase.yml`); schema em `app/db/schema.sql`
  criado pelo app no startup (`server/db.py`, idempotente).

### Deploy do app (DABs) — Lakebase 100% no bundle
- `resources/app.yml` (recurso `apps`) + `resources/lakebase.yml` (Lakebase Autoscaling:
  `postgres_projects/branches/endpoints/databases`) + `app/app.yaml` (env; PG* via binding).
- **Lakebase Autoscaling É endereçável no DAB** via os resources `postgres_*` (o que NÃO existe
  como resource é o CDF). O app binda o banco por `app.resources[].postgres` = `{branch, database,
  permission: CAN_CONNECT_AND_CREATE}` → injeta PGHOST/PGPORT/PGDATABASE/PGUSER e dá acesso ao SP.
- Senha do Postgres: *database credential* gerada em runtime (`POST /api/2.0/postgres/credentials`
  com o endpoint da branch do target — env `LAKEBASE_ENDPOINT_PATH`).
- Tabela `estimates`: criada pelo **app no startup** (idempotente, `server/db.py`); como o SP tem
  CAN_CONNECT_AND_CREATE, ele vira **dono** da tabela → read/write sem grant extra.
- Referência `model_ref_snapshot` (CTAS de `v_model_ref`) recriada pela task `create_model_ref_snapshot`
  do job `leaderboard`; SELECT ao SP via `app.resources[].uc_securable` (dispensa GRANT manual).
- **Fluxo de deploy**: `bundle deploy -t dev` → `bundle run leaderboard -t dev` (views + snapshot)
  → `bundle run ai_savings_app -t dev` (sobe o app). Sem scripts manuais.
- `app/scripts/{init_lakebase,setup_app_lakebase,grant_app_sp}` ficam como referência/fallback,
  fora do fluxo de deploy (o bundle + startup do app cobrem tudo).
- **Embed da aba de acompanhamento** exige habilitar *embedding de dashboards AI/BI* no workspace
  (config de admin); sem isso, mostra fallback "Abrir no Databricks" (comportamento esperado).

## Limitações conhecidas / próximos

- **Combo diário multi-linha** (N linhas coloridas por seleção) não é viável nativo (combo não
  faz color dinâmico + bars); ficou **linha única**. v2 = custom Vega-Lite (long format) ou
  line chart com o real também como linha.
- **Counter não colore o valor por sinal** (verde/vermelho) nativamente.
- **Fase 3** (não iniciada): exercício reverso — cliente traz consumo single-provider →
  estimar savings de um blend via AI Gateway (mesmo de-para AA, para modelos mais baratos de
  performance equivalente).

## Reuso no app (calculadora)

Consultar direto **`perdomo_demos_catalog.ai_savings.v_model_usage_daily`** (real + tokens) e
**`v_aa_model_ref`** (performance/preço AA). As fórmulas acima (taxa efetiva, de-para por
intelligence, reprecificação in/out/cache) são a lógica a portar. Padrões SQL prontos estão
nos `queryLines` dos datasets do `ai_savings.lvdash.json` e nos arquivos `ddl/`.
