# ai-savings

Coleta o leaderboard de custo x performance de modelos da
[Artificial Analysis](https://artificialanalysis.ai) (Data API, Free Tier) e grava
os scores numéricos em uma tabela Delta no Unity Catalog, guardando um snapshot a cada
execução para manter histórico.

## Estrutura

```
.
├── databricks.yml            # bundle: variáveis (catalog/schema/table/secret) e targets dev/prod
├── aa_leaderboard.py         # notebook: busca a API e insere o snapshot na tabela Delta
└── resources/
    └── leaderboard.job.yml   # job quinzenal (segundas 8h)
```

## Como funciona

- O notebook busca todos os modelos do endpoint free (com retry simples de rede).
- Calcula três scores de 1 a 4 (`0` = sem dado): **custo**, **performance** e **velocidade**.
- Insere (`append`) um snapshot em `${catalog}.${schema}.${table}`, carimbado por `captured_at`.
- O job roda toda segunda às 8h; o notebook pula semanas alternadas para ficar quinzenal.

## Pré-requisitos

1. Definir o `profile` do workspace nos targets do `databricks.yml`.
2. Criar o secret com a chave da API (uma vez), batendo com os defaults do bundle:

   ```bash
   databricks secrets create-scope ai_savings --profile <PROFILE>
   databricks secrets put-secret ai_savings aa_api_key --profile <PROFILE>
   ```

3. Ajustar `catalog` / `schema` / `table` no `databricks.yml` conforme o destino.

## Deploy

```bash
databricks bundle validate --target dev --profile <PROFILE>
databricks bundle deploy   --target dev --profile <PROFILE>
databricks bundle run leaderboard --target dev --profile <PROFILE>
```

Fonte dos dados: [Artificial Analysis](https://artificialanalysis.ai).
