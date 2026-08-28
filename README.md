# ai-savings

Estima a **economia potencial em IA** de um cliente Databricks: compara o custo real de
consumo de LLMs (faturado pela Databricks) com o custo estimado se **os mesmos tokens do
período rodassem em um único modelo**. Entrega um dashboard AI/BI sobre system tables.

Inclui também um coletor quinzenal do leaderboard custo × performance da
[Artificial Analysis](https://artificialanalysis.ai) (histórico em tabela Delta), pensado
como base para evoluções futuras.

## Estrutura

```
.
├── databricks.yml            # bundle: variáveis (catalog/schema/warehouse/secret) e targets dev/prod
├── ai_savings.lvdash.json    # dashboard AI/BI "AI Savings"
├── aa_leaderboard.py         # notebook: coleta o leaderboard da Artificial Analysis
├── ddl/
│   └── v_model_usage_daily.sql   # view: fato diário por modelo (custo real + tokens)
└── resources/
    ├── dashboard.yml         # recurso DABs do dashboard
    └── leaderboard.job.yml   # job quinzenal do leaderboard
```

## Como funciona a estimativa

- **Custo real** (mesma lógica validada do dashboard oficial *AI Gateway Usage Analytics*):
  - PPT / Databricks-hosted: `system.billing.usage` × `system.billing.list_prices` (DBU × $/DBU).
  - External Models: `system.ai_gateway.external_model_spend` (já em USD).
- **Tokens** (input/output/cache): `system.ai_gateway.usage`.
- A view `v_model_usage_daily` une custo + tokens no grão **dia × modelo × workspace**.
- **Simulação "modelo único"**: usa o **custo efetivo agregado** de cada modelo —
  `taxa[m] = custo_real[m] / tokens[m]` (sobre todo o histórico do workspace, para ser
  estável e sempre disponível). O custo simulado do período = `tokens_do_período × taxa[m]`.

  > As system tables **não** expõem preço por token separado de input/output/cache
  > (o $/DBU é plano; a quebra por tipo existe só como *contagem* de tokens). A taxa efetiva
  > é uma **proxy direcional** — o caching fica embutido na taxa realizada de cada modelo,
  > mas não há separação input/output/cache. É a única abordagem 100% consistente (real e
  > simulado na mesma régua de faturamento Databricks). Escopo: só consumo **cobrado por
  > token** (provisioned-throughput e batch ficam de fora).

## Dashboard

- **3 caixas de valor**: real gasto · estimado (modelo único) · economia/prejuízo.
- **Custo diário por modelo** (barras empilhadas) + **linha** do estimado modelo único.
- **Tokens diários por modelo** (barras empilhadas).
- **Comparativo do período**: real vs. cada modelo único selecionado.
- **Filtros**: período, workspace, modelos usados, modelo p/ simular, modelos p/ comparar.

> Como as system tables aqui são account-level (vários workspaces), **selecione seu
> workspace** no filtro. O tool só se aplica a workspaces com `ai_gateway.usage` populado
> (é de lá que vêm as contagens de token).

## Pré-requisitos

1. Ajustar `profile`, `catalog`, `schema` e `warehouse_id` no `databricks.yml`.
2. Criar a **view** no catálogo (o dashboard depende dela). Ela está versionada em `ddl/`:

   ```bash
   databricks experimental aitools tools query \
     --profile <PROFILE> --warehouse <WAREHOUSE_ID> \
     --file ddl/v_model_usage_daily.sql
   ```

   > Se mudar o catálogo/schema de destino, ajuste o nome totalmente qualificado no topo do
   > `ddl/v_model_usage_daily.sql` **e** nos datasets do `ai_savings.lvdash.json` (o DABs não
   > faz substituição de variável dentro do JSON do dashboard).

3. (Opcional, para o leaderboard) criar o secret com a chave da API:

   ```bash
   databricks secrets create-scope ai_savings --profile <PROFILE>
   databricks secrets put-secret ai_savings aa_api_key --profile <PROFILE>
   ```

## Deploy

```bash
databricks bundle validate --target dev --profile <PROFILE>
databricks bundle deploy   --target dev --profile <PROFILE>   # cria dashboard + job
```

Fonte dos dados: system tables da Databricks e [Artificial Analysis](https://artificialanalysis.ai).
