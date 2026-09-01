"""Motor de cálculo de economia — função pura, sem I/O (testável isoladamente).

Régua (confirmada com o usuário):
- Distribuição em TOKENS (input + output + cache_read + cache_write, todos faturáveis).
- Ambas as colunas (atual e sugerido) precificadas pela lista Artificial Analysis, para
  isolar o efeito do rebalanceamento (% alvo) + otimização (% passível). O gasto reportado
  em US$ é só âncora, não entra no cálculo.
- Os 4 campos de token são INDEPENDENTES e aditivos (semântica de faturamento
  Anthropic/OpenAI: cache read/write são linhas à parte do input).
- Premissa: todo modelo envolvido existe na Databricks.
  * % alvo  = rebalancear tokens entre tiers; a fatia não-otimizada permanece nos modelos
    do cliente naquele tier (taxa efetiva AA do tier).
  * % passível = trocar por modelo de performance EQUIVALENTE (intelligence >= repr - tol)
    porém mais barato, filtrando on_databricks = true.

A referência de modelo (`model_ref`) é injetada (lista de dicts vinda de v_model_ref):
slug_norm, model, provider, intelligence, price_input, price_output, price_cache_read,
price_cache_write, on_databricks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Configuração (ajustável). Bandas de intelligence do índice AA (~0-65 nesta base).
# ---------------------------------------------------------------------------
TIERS = ("alta", "media", "baixa")
TIER_LABELS = {"alta": "Alta", "media": "Média", "baixa": "Baixa"}
ALTA_MIN = 50.0    # intelligence >= 50 -> Alta
MEDIA_MIN = 28.0   # 28 <= intelligence < 50 -> Média ; < 28 -> Baixa
# "performance equivalente": o candidato de otimização pode ter até EQUIV_TOLERANCE
# pontos de intelligence A MENOS que o modelo representativo do tier.
EQUIV_TOLERANCE = 3.0


def norm_slug(name: str) -> str:
    """Mesma normalização das views: LOWER + colapsa espaços/pontos em '-'."""
    return re.sub(r"[ .]+", "-", (name or "").strip().lower())


def tier_of(intelligence: float | None) -> str:
    if intelligence is None:
        return "media"  # sem referência: tier neutro
    if intelligence >= ALTA_MIN:
        return "alta"
    if intelligence >= MEDIA_MIN:
        return "media"
    return "baixa"


def _price_get(rec: dict, key: str, fallback_key: str = "price_input") -> float:
    """Preço por 1M; cache cai para price_input quando nulo (igual à Fase 1)."""
    v = rec.get(key)
    if v is None:
        v = rec.get(fallback_key)
    return float(v or 0.0)


def reprice(tokens: dict, rec: dict) -> float:
    """Custo USD para um mix de tokens {input,output,cache_read,cache_write} a preço AA."""
    pin = float(rec.get("price_input") or 0.0)
    pout = float(rec.get("price_output") or 0.0)
    pcr = _price_get(rec, "price_cache_read")
    pcw = _price_get(rec, "price_cache_write")
    return (
        tokens.get("input", 0.0) * pin
        + tokens.get("output", 0.0) * pout
        + tokens.get("cache_read", 0.0) * pcr
        + tokens.get("cache_write", 0.0) * pcw
    ) / 1_000_000.0


def _empty_mix() -> dict:
    return {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0}


def _add_mix(dst: dict, src: dict, scale: float = 1.0) -> None:
    for k in dst:
        dst[k] += src.get(k, 0.0) * scale


def _mix_total(mix: dict) -> float:
    return sum(mix.values())


def _scaled_mix(mix: dict, target_total: float) -> dict:
    """Reescala um mix mantendo as proporções para somar target_total tokens."""
    cur = _mix_total(mix)
    if cur <= 0:
        return _empty_mix()
    f = target_total / cur
    return {k: v * f for k, v in mix.items()}


@dataclass
class TierAgg:
    tier: str
    models: list[str] = field(default_factory=list)     # rótulos amigáveis
    slugs: list[str] = field(default_factory=list)
    mix: dict = field(default_factory=_empty_mix)        # tokens por tipo (atual)
    cost: float = 0.0                                    # custo AA atual do tier
    intel_num: float = 0.0                               # p/ média ponderada
    intel_den: float = 0.0

    @property
    def tokens(self) -> float:
        return _mix_total(self.mix)

    @property
    def intelligence(self) -> float | None:
        return (self.intel_num / self.intel_den) if self.intel_den else None

    @property
    def effective_rate(self) -> float:
        """$ por token (AA) do mix atual do tier — usado na fatia não-otimizada."""
        t = self.tokens
        return (self.cost / t) if t else 0.0


def _pick_optimized_model(ref_by_slug: dict, rep_intel: float | None, opt_mix: dict) -> dict | None:
    """Modelo mais barato, disponível na Databricks, de performance >= (repr - tolerância)."""
    floor = (rep_intel - EQUIV_TOLERANCE) if rep_intel is not None else -1.0
    best, best_cost = None, None
    for rec in ref_by_slug.values():
        if not rec.get("on_databricks"):
            continue
        intel = rec.get("intelligence")
        if intel is None or intel < floor:
            continue
        c = reprice(opt_mix, rec)
        if best_cost is None or c < best_cost:
            best, best_cost = rec, c
    return best


def compute(inputs: list[dict], budget: dict, model_ref: list[dict],
            cache_applies: bool = True) -> dict:
    """Calcula baseline (atual) x alvo (sugerido) e a economia.

    inputs: [{model, input, output, cache_read, cache_write, spend_usd}]
    budget: {"alta": {"pct_alvo": 53, "pct_optimizable": 10}, ...}  (% em pontos 0-100)
    model_ref: linhas de v_model_ref.
    """
    ref_by_slug = {norm_slug(r["slug_norm"]): r for r in model_ref}

    warnings: list[str] = []
    reported_spend = 0.0
    baseline_cost = 0.0
    current_breakdown: list[dict] = []
    tiers: dict[str, TierAgg] = {t: TierAgg(tier=t) for t in TIERS}

    # --- 1) resolve + classifica + repreça cada modelo do cliente (baseline) ---
    for row in inputs:
        name = row.get("model", "")
        slug = norm_slug(name)
        rec = ref_by_slug.get(slug)
        reported_spend += float(row.get("spend_usd") or 0.0)
        if rec is None:
            warnings.append(f"Modelo sem correspondência na Artificial Analysis (excluído): {name}")
            continue

        mix = {
            "input": float(row.get("input") or 0.0),
            "output": float(row.get("output") or 0.0),
            "cache_read": 0.0 if not cache_applies else float(row.get("cache_read") or 0.0),
            "cache_write": 0.0 if not cache_applies else float(row.get("cache_write") or 0.0),
        }
        cost = reprice(mix, rec)
        baseline_cost += cost
        t = tier_of(rec.get("intelligence"))
        agg = tiers[t]
        label = rec.get("model") or name
        if label not in agg.models:
            agg.models.append(label)
        if slug not in agg.slugs:
            agg.slugs.append(slug)
        _add_mix(agg.mix, mix)
        agg.cost += cost
        intel = rec.get("intelligence")
        if intel is not None:
            agg.intel_num += float(intel) * _mix_total(mix)
            agg.intel_den += _mix_total(mix)
        current_breakdown.append({
            "model": label, "slug": slug, "tier": t,
            "tokens": _mix_total(mix), "cost": cost,
        })

    total_tokens = sum(t.tokens for t in tiers.values())
    if total_tokens <= 0:
        return {
            "baseline_cost": 0.0, "target_cost": 0.0, "savings": 0.0, "savings_pct": 0.0,
            "reported_spend": reported_spend, "total_tokens": 0.0, "warnings": warnings,
            "tiers": [], "current_breakdown": [], "target_breakdown": [],
        }

    # --- 2) cenário alvo por tier ---
    target_cost = 0.0
    tiers_out: list[dict] = []
    target_breakdown: list[dict] = []

    for t in TIERS:
        agg = tiers[t]
        b = budget.get(t, {}) or {}
        pct_atual = 100.0 * agg.tokens / total_tokens
        pct_alvo = float(b.get("pct_alvo", pct_atual))
        pct_opt = float(b.get("pct_optimizable", 0.0))

        target_tokens = total_tokens * pct_alvo / 100.0
        # o mix de tipos do tier alvo herda as proporções do tier atual (fallback: sem tokens)
        base_mix = agg.mix if agg.tokens > 0 else _empty_mix()
        opt_tokens = target_tokens * pct_opt / 100.0
        non_opt_tokens = target_tokens - opt_tokens

        # fatia não-otimizada: mantém os modelos do cliente (taxa efetiva AA do tier)
        non_opt_cost = agg.effective_rate * non_opt_tokens

        # fatia otimizada: modelo mais barato de performance equivalente na Databricks
        opt_mix = _scaled_mix(base_mix, opt_tokens) if opt_tokens > 0 else _empty_mix()
        chosen = _pick_optimized_model(ref_by_slug, agg.intelligence, opt_mix) if opt_tokens > 0 else None
        opt_cost = reprice(opt_mix, chosen) if chosen else 0.0

        tier_target_cost = non_opt_cost + opt_cost
        target_cost += tier_target_cost

        # séries do gráfico (coluna sugerido, empilhada por segmento)
        if non_opt_tokens > 0 and agg.models:
            target_breakdown.append({
                "tier": t, "kind": "base", "tokens": non_opt_tokens, "cost": non_opt_cost,
                "model": ", ".join(agg.models),
            })
        if opt_tokens > 0 and chosen:
            target_breakdown.append({
                "tier": t, "kind": "optimized", "tokens": opt_tokens, "cost": opt_cost,
                "model": chosen.get("model"), "slug": chosen.get("slug_norm"),
                "provider": chosen.get("provider"), "intelligence": chosen.get("intelligence"),
            })

        tiers_out.append({
            "tier": t, "label": TIER_LABELS[t],
            "models": agg.models, "slugs": agg.slugs,
            "intelligence": agg.intelligence,
            "pct_atual": round(pct_atual, 2), "pct_alvo": pct_alvo, "pct_optimizable": pct_opt,
            "current": {"tokens": agg.tokens, "cost": agg.cost},
            "target": {
                "tokens": target_tokens,
                "non_optimized": {"tokens": non_opt_tokens, "cost": non_opt_cost,
                                  "model": ", ".join(agg.models) if agg.models else None},
                "optimized": ({"tokens": opt_tokens, "cost": opt_cost,
                               "model": chosen.get("model"), "slug": chosen.get("slug_norm"),
                               "provider": chosen.get("provider"),
                               "intelligence": chosen.get("intelligence")} if chosen else None),
                "cost": tier_target_cost,
            },
        })

    savings = baseline_cost - target_cost
    savings_pct = (100.0 * savings / baseline_cost) if baseline_cost else 0.0

    return {
        "baseline_cost": baseline_cost,
        "target_cost": target_cost,
        "savings": savings,
        "savings_pct": savings_pct,
        "reported_spend": reported_spend,
        "total_tokens": total_tokens,
        "warnings": warnings,
        "tiers": tiers_out,
        "current_breakdown": current_breakdown,
        "target_breakdown": target_breakdown,
    }


def default_budget(inputs: list[dict], model_ref: list[dict], cache_applies: bool = True) -> dict:
    """Orçamento default: % alvo = % atual, % passível = 0 (ponto de partida da UI)."""
    res = compute(inputs, {}, model_ref, cache_applies)
    return {tr["tier"]: {"pct_alvo": tr["pct_atual"], "pct_optimizable": 0.0}
            for tr in res["tiers"] if tr["current"]["tokens"] > 0}
