# ai-savings

Dashboard AI/BI, sobre system tables, que estima a **economia potencial em IA** de um
cliente Databricks:

- **Modelo único** — quanto custaria rodar os mesmos tokens do período em um só modelo
  (custo efetivo agregado, na régua de faturamento Databricks).
- **Provider único (direto)** — quanto custaria indo direto num provider só (OpenAI,
  Anthropic, …), via de-para por performance/preço da [Artificial Analysis](https://artificialanalysis.ai).
- **Por harness** — consumo em dólares rateado por Claude Code, Codex, OpenCode, etc.

## Estrutura

```
.
├── databricks.yml            # bundle: variáveis (catalog/schema/warehouse/secret) + targets dev/prod
├── ai_savings.lvdash.json    # dashboard AI/BI "AI Savings"
├── aa_leaderboard.py         # notebook: coleta o leaderboard da Artificial Analysis
├── ddl/
│   ├── v_model_usage_daily.sql   # view: fato diário por modelo (custo real + tokens)
│   └── v_aa_model_ref.sql        # view: referência AA (performance + preços) p/ o de-para
└── resources/
    ├── dashboard.yml         # recurso DABs do dashboard
    └── leaderboard.job.yml   # job semanal: coleta + cria as views na 1ª execução
```

## Setup e deploy

Fluxo centralizado — depois disto o job roda sozinho e o dashboard fica pronto:

1. **Ajuste o `databricks.yml`**: `profile`, `catalog`, `schema`, `warehouse_id`.
2. **Crie o secret** com a chave da API da Artificial Analysis (nomes batem com os defaults
   `secret_scope=ai_savings` / `secret_key=aa_api_key`):

   ```bash
   databricks secrets create-scope ai_savings --profile <PROFILE>
   databricks secrets put-secret  ai_savings aa_api_key --profile <PROFILE>
   ```

   Alternativa em notebook Python (`dbutils.secrets` só *lê*; a criação é via SDK):

   ```python
   from databricks.sdk import WorkspaceClient
   w = WorkspaceClient()
   w.secrets.create_scope(scope="ai_savings")               # ignore se já existir
   w.secrets.put_secret(scope="ai_savings", key="aa_api_key", string_value="<SUA_API_KEY>")
   ```

3. **Deploy** (cria dashboard + job):

   ```bash
   databricks bundle validate --target dev --profile <PROFILE>
   databricks bundle deploy   --target dev --profile <PROFILE>
   ```

4. **Rode o job uma vez** — coleta a AA, cria o schema/tabela e, como as views ainda não
   existem, as duas tasks de DDL rodam (em paralelo) e criam as views:

   ```bash
   databricks bundle run leaderboard --target dev --profile <PROFILE>
   ```

5. **Abra o dashboard.** Nas próximas execuções semanais o job só coleta o snapshot; as
   tasks de DDL são puladas porque as views já existem (condition task `views_missing`).

6. **Deploy do app calculadora (Fase 2).** Além do dashboard, o repositório traz um
   **Databricks App** (calculadora de economia, `app/`) que **precisa ser deployado à parte** —
   ele não sobe junto com o dashboard. Depois do `bundle deploy`, suba o app:

   ```bash
   databricks bundle run ai_savings_app --target dev --profile <PROFILE>
   ```

> As views e o dashboard usam o catálogo/schema **fully-qualified** no código. Se mudar o
> destino, ajuste o topo dos arquivos em `ddl/` **e** os datasets do `ai_savings.lvdash.json`
> (o DABs não substitui variável dentro do JSON do dashboard).

## Como funciona (resumo)

- **Custo real** (lógica do dashboard oficial *AI Gateway Usage Analytics*): PPT via
  `system.billing.usage` × `list_prices` (DBU × $/DBU) + External via
  `ai_gateway.external_model_spend`; **tokens** de `ai_gateway.usage`. Unificados na
  `v_model_usage_daily` (grão dia × modelo × workspace).
- **Modelo único**: taxa efetiva `custo_real[m] / tokens[m]` × tokens do período.
- **Provider único**: para cada modelo real, escolhe o modelo do provider-alvo com
  `intelligence` mais próxima (AA) e reprecifica input/output/cache pelo preço direto dele.
- As system tables aqui são account-level — **selecione seu workspace** no filtro; o tool só
  se aplica a workspaces com `ai_gateway.usage` populado.

Fonte dos dados: system tables da Databricks e [Artificial Analysis](https://artificialanalysis.ai).
