"""Testes do motor de cálculo — valores conferidos à mão.

Rodar: uv run --with pytest python -m pytest app/tests/test_engine.py -q
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # app/ no path

from server import engine  # noqa: E402


# Fixture controlada (números redondos para conferência manual). intelligence escolhida
# para cair nas bandas: Alta >= 50, Média 28-50, Baixa < 28.
REF = [
    {"slug_norm": "model-a", "model": "Model A", "provider": "X", "intelligence": 60.0,
     "price_input": 10.0, "price_output": 30.0, "price_cache_read": 1.0,
     "price_cache_write": 2.0, "on_databricks": True},
    {"slug_norm": "model-b", "model": "Model B", "provider": "X", "intelligence": 40.0,
     "price_input": 3.0, "price_output": 9.0, "price_cache_read": None,
     "price_cache_write": None, "on_databricks": True},
    {"slug_norm": "model-c", "model": "Model C", "provider": "X", "intelligence": 20.0,
     "price_input": 1.0, "price_output": 2.0, "price_cache_read": None,
     "price_cache_write": None, "on_databricks": True},
    # Alternativa barata de performance equivalente ao A (intel 58 >= 60-3): alvo de otimização.
    {"slug_norm": "cheap-alta", "model": "Cheap Alta", "provider": "OSS", "intelligence": 58.0,
     "price_input": 1.0, "price_output": 3.0, "price_cache_read": None,
     "price_cache_write": None, "on_databricks": True},
    # Barato mas NÃO disponível na Databricks: nunca deve ser escolhido.
    {"slug_norm": "cheap-off", "model": "Cheap Off", "provider": "OSS", "intelligence": 59.0,
     "price_input": 0.1, "price_output": 0.1, "price_cache_read": None,
     "price_cache_write": None, "on_databricks": False},
]

# 1M tokens de cada tipo simplifica: custo (USD) = preço por 1M.
M = 1_000_000
INPUTS = [
    {"model": "Model A", "input": 1 * M, "output": 1 * M, "cache_read": 0,
     "cache_write": 0, "spend_usd": 40},
    {"model": "Model B", "input": 1 * M, "output": 0, "cache_read": 0,
     "cache_write": 0, "spend_usd": 3},
    {"model": "Model C", "input": 1 * M, "output": 0, "cache_read": 0,
     "cache_write": 0, "spend_usd": 1},
]


def _tier(res, name):
    return next(t for t in res["tiers"] if t["tier"] == name)


def test_baseline_e_classificacao():
    res = engine.compute(INPUTS, {}, REF)
    # baseline AA: A=(10+30)=40, B=3, C=1 -> 44
    assert round(res["baseline_cost"], 6) == 44.0
    assert res["reported_spend"] == 44.0  # aqui coincidem, mas são conceitos distintos
    assert res["total_tokens"] == 4 * M
    assert _tier(res, "alta")["pct_atual"] == 50.0
    assert _tier(res, "media")["pct_atual"] == 25.0
    assert _tier(res, "baixa")["pct_atual"] == 25.0
    assert _tier(res, "alta")["models"] == ["Model A"]


def test_otimizacao_total_do_tier_alta():
    # % alvo = % atual; Alta 100% otimizável -> troca A por Cheap Alta (não Cheap Off).
    budget = {"alta": {"pct_alvo": 50, "pct_optimizable": 100},
              "media": {"pct_alvo": 25, "pct_optimizable": 0},
              "baixa": {"pct_alvo": 25, "pct_optimizable": 0}}
    res = engine.compute(INPUTS, budget, REF)
    # Alta 2M (input 1M + output 1M) repreçado por Cheap Alta = (1 + 3) = 4
    # Média 3 + Baixa 1 -> target 8 ; savings 36 (81.8%)
    assert round(res["target_cost"], 6) == 8.0
    assert round(res["savings"], 6) == 36.0
    assert round(res["savings_pct"], 1) == 81.8
    # de-para por modelo: Model A -> Cheap Alta (não Cheap Off, fora da Databricks)
    sub = _tier(res, "alta")["models_detail"][0]["substitute"]
    assert sub["model"] == "Cheap Alta"


def test_rebalanceamento_sem_otimizacao():
    # Desloca consumo de Alta (caro) para Média; nenhuma otimização de modelo.
    budget = {"alta": {"pct_alvo": 25, "pct_optimizable": 0},
              "media": {"pct_alvo": 50, "pct_optimizable": 0},
              "baixa": {"pct_alvo": 25, "pct_optimizable": 0}}
    res = engine.compute(INPUTS, budget, REF)
    # Alta taxa efetiva = 40/2M ; 1M -> 20 ; Média 3/1M ; 2M -> 6 ; Baixa 1 -> target 27
    assert round(res["target_cost"], 6) == 27.0
    assert round(res["savings"], 6) == 17.0


def test_cache_nao_se_aplica_zera_cache():
    inputs = [{"model": "Model A", "input": 1 * M, "output": 0, "cache_read": 5 * M,
               "cache_write": 5 * M, "spend_usd": 0}]
    com = engine.compute(inputs, {}, REF, cache_applies=True)
    sem = engine.compute(inputs, {}, REF, cache_applies=False)
    # com cache: input 10 + cache_read 5*1 + cache_write 5*2 = 10+5+10 = 25
    assert round(com["baseline_cost"], 6) == 25.0
    # sem cache: só input 1M*10/1M = 10
    assert round(sem["baseline_cost"], 6) == 10.0


def test_modelo_sem_match_gera_warning():
    inputs = INPUTS + [{"model": "Inexistente XYZ", "input": 1 * M, "output": 0,
                        "cache_read": 0, "cache_write": 0, "spend_usd": 99}]
    res = engine.compute(inputs, {}, REF)
    assert any("Inexistente XYZ" in w for w in res["warnings"])
    assert res["baseline_cost"] == 44.0  # o inexistente não entra no custo
    assert res["reported_spend"] == 143.0  # mas seu gasto reportado conta na âncora


def test_de_para_por_modelo_independente():
    # Dois modelos no MESMO tier (Alta) com recomendações diferentes: o piso é a
    # intelligence de cada modelo - 3, não a média do tier.
    ref = REF + [
        {"slug_norm": "model-d", "model": "Model D", "provider": "X", "intelligence": 52.0,
         "price_input": 8.0, "price_output": 24.0, "price_cache_read": None,
         "price_cache_write": None, "on_databricks": True},
        {"slug_norm": "cheap-mid", "model": "Cheap Mid", "provider": "OSS", "intelligence": 51.0,
         "price_input": 0.5, "price_output": 1.5, "price_cache_read": None,
         "price_cache_write": None, "on_databricks": True},
    ]
    inputs = [
        {"model": "Model A", "input": 1 * M, "output": 1 * M, "cache_read": 0, "cache_write": 0, "spend_usd": 0},
        {"model": "Model D", "input": 1 * M, "output": 1 * M, "cache_read": 0, "cache_write": 0, "spend_usd": 0},
    ]
    res = engine.compute(inputs, {"alta": {"pct_alvo": 100, "pct_optimizable": 100}}, ref)
    sub = {d["model"]: d["substitute"]["model"] for d in _tier(res, "alta")["models_detail"] if d["substitute"]}
    assert sub["Model A"] == "Cheap Alta"  # piso 57 -> só Cheap Alta (58) qualifica
    assert sub["Model D"] == "Cheap Mid"   # piso 49 -> Cheap Mid (51) é mais barato


def test_norm_slug_particao():
    # gêmeo Python da expressão match_key das views: precisam bater sempre.
    assert engine.norm_slug("Claude Opus 4.8") == "claude-opus-4-8"
    # recupera divergência de ORDEM AA<->Databricks
    assert engine.norm_slug("claude-4-5-sonnet") == engine.norm_slug("claude-sonnet-4-5")
    # NÃO colide inversão de versão (ordem dos números preservada)
    assert engine.norm_slug("claude-sonnet-4-5") != engine.norm_slug("claude-sonnet-5-4")
    # underscore/espaço colapsam igual
    assert engine.norm_slug("databricks_claude_opus_4_8") == "databricks-claude-opus-4-8"


def test_default_budget():
    b = engine.default_budget(INPUTS, REF)
    assert b["alta"]["pct_alvo"] == 50.0
    assert b["alta"]["pct_optimizable"] == 0.0
