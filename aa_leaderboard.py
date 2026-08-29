# Databricks notebook source
# MAGIC %md
# MAGIC # Artificial Analysis — leaderboard custo x performance
# MAGIC
# MAGIC Busca os modelos na Data API (Free Tier) e insere os scores numéricos
# MAGIC (custo / performance / velocidade) em uma tabela Delta append-only,
# MAGIC guardando um snapshot (`captured_at`) a cada execução quinzenal.
# MAGIC
# MAGIC Catálogo, schema, tabela e o secret com a chave da API são definidos pelo bundle.
# MAGIC Fonte: [Artificial Analysis](https://artificialanalysis.ai).

# COMMAND ----------

dbutils.widgets.text("catalog", "main")
dbutils.widgets.text("schema", "ai_savings")
dbutils.widgets.text("table", "aa_leaderboard")
dbutils.widgets.text("secret_scope", "ai_savings")
dbutils.widgets.text("secret_key", "aa_api_key")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
target_table = f"{catalog}.{schema}.{dbutils.widgets.get('table')}"
api_key = dbutils.secrets.get(dbutils.widgets.get("secret_scope"), dbutils.widgets.get("secret_key"))

# COMMAND ----------

import json
import time
import urllib.request

BASE_URL = "https://artificialanalysis.ai/api/v2"
ENDPOINT = "/language/models/free"  # Free Tier

# Blend de preço: peso 3 para input, 1 para output (mistura típica de workload).
INPUT_WEIGHT, OUTPUT_WEIGHT = 3, 1

# Thresholds dos scores (1..4). Valores crescentes.
INTEL_TH = [30, 45, 58]      # intelligence index (0-100): maior = melhor
PRICE_TH = [1.0, 5.0, 15.0]  # preço blended (USD / 1M tokens): maior = mais caro
SPEED_TH = [40, 90, 180]     # tokens/s: maior = mais rápido


def fetch_models(api_key):
    """Percorre todas as páginas do endpoint free, com retry simples de rede."""
    models, page = [], 1
    while True:
        req = urllib.request.Request(f"{BASE_URL}{ENDPOINT}?page={page}",
                                     headers={"x-api-key": api_key})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(1.5 * (attempt + 1))  # backoff antes de tentar de novo
        models.extend(payload.get("data", []))
        if not payload.get("pagination", {}).get("has_more"):
            break
        page += 1
    return models


def get(d, *path, default=None):
    """Acesso aninhado explícito: get(m, 'pricing', 'price_1m_input_tokens')."""
    cur = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur if cur is not None else default


def num(v):
    """Coerção para float (mantém None) — evita ambiguidade de tipo no Spark."""
    return float(v) if v is not None else None


def blended_price(m):
    inp = get(m, "pricing", "price_1m_input_tokens")
    out = get(m, "pricing", "price_1m_output_tokens")
    if inp is None or out is None:
        return None
    return (inp * INPUT_WEIGHT + out * OUTPUT_WEIGHT) / (INPUT_WEIGHT + OUTPUT_WEIGHT)


def bucket(value, thresholds):
    """Score 1..4 conforme o valor cai nos thresholds; 0 se sem dado."""
    if value is None:
        return 0
    return min(1 + sum(value > t for t in thresholds), 4)

# COMMAND ----------

rows = []
for m in fetch_models(api_key):
    intel = get(m, "evaluations", "artificial_analysis_intelligence_index")
    tps = get(m, "performance", "median_output_tokens_per_second")
    price = blended_price(m)
    rows.append({
        "provider": get(m, "model_creator", "name", default="?"),
        "model": get(m, "name", default=get(m, "slug", default="?")),
        "slug": get(m, "slug"),
        "intelligence": num(intel),
        "tokens_per_s": num(tps),
        "ttft_s": num(get(m, "performance", "median_time_to_first_token_seconds")),
        "e2e_s": num(get(m, "performance", "median_end_to_end_response_time_seconds")),
        # Preços por 1M tokens (base do de-para de custo da fase 2).
        "price_input": num(get(m, "pricing", "price_1m_input_tokens")),
        "price_output": num(get(m, "pricing", "price_1m_output_tokens")),
        "blended_price": num(price),
        # Objeto pricing cru: garante que preços de cache (nome de campo não
        # documentado) fiquem preservados para parsing posterior.
        "pricing_json": json.dumps(get(m, "pricing", default={}) or {}),
        "cost_per_task": num(get(m, "artificial_analysis_intelligence_index_cost",
                                  "cost_per_task", "total_cost")),
        "cost_score": bucket(price, PRICE_TH),
        "perf_score": bucket(intel, INTEL_TH),
        "speed_score": bucket(tps, SPEED_TH),
    })

print(f"{len(rows)} modelos recebidos da API.")

# COMMAND ----------

from pyspark.sql.functions import current_timestamp
from pyspark.sql.types import (DoubleType, LongType, StringType, StructField,
                               StructType)

SCHEMA = StructType([
    StructField("provider", StringType()),
    StructField("model", StringType()),
    StructField("slug", StringType()),
    StructField("intelligence", DoubleType()),
    StructField("tokens_per_s", DoubleType()),
    StructField("ttft_s", DoubleType()),
    StructField("e2e_s", DoubleType()),
    StructField("price_input", DoubleType()),
    StructField("price_output", DoubleType()),
    StructField("blended_price", DoubleType()),
    StructField("pricing_json", StringType()),
    StructField("cost_per_task", DoubleType()),
    StructField("cost_score", LongType()),
    StructField("perf_score", LongType()),
    StructField("speed_score", LongType()),
])

# captured_at carimba o momento da execução — é a dimensão de histórico.
df = spark.createDataFrame(rows, schema=SCHEMA).withColumn("captured_at", current_timestamp())

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
# Tabela Delta append-only: cada execução quinzenal insere um novo snapshot.
df.write.format("delta").mode("append").saveAsTable(target_table)

print(f"Snapshot de {len(rows)} modelos inserido em {target_table}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sinaliza se as views precisam ser criadas
# MAGIC Seta um task value lido pela condition task do job: as tasks de DDL só rodam
# MAGIC quando alguma das views ainda não existe (primeira execução após o deploy).

# COMMAND ----------

REQUIRED_VIEWS = {"v_model_usage_daily", "v_aa_model_ref"}
existing_views = {
    r.viewName for r in spark.sql(f"SHOW VIEWS IN {catalog}.{schema}").collect()
}
create_needed = "true" if not REQUIRED_VIEWS <= existing_views else "false"

try:
    dbutils.jobs.taskValues.set(key="create_needed", value=create_needed)
except Exception:
    pass  # fora de um job (execução interativa) — task values não se aplicam

print(f"create_needed = {create_needed}")

# COMMAND ----------

# Ordenado: melhor performance primeiro; empate desempata por menor custo.
display(df.orderBy(df.perf_score.desc(), df.cost_score.asc()))
