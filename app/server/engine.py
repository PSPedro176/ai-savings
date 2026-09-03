"""Motor de cálculo de economia — função pura, sem I/O (testável isoladamente).

Régua (confirmada com o usuário):
- Distribuição em TOKENS (input + output + cache_read + cache_write, todos faturáveis).
- Ambas as colunas (atual e sugerido) precificadas pela lista Artificial Analysis, para
  isolar o efeito do rebalanceamento (% alvo) + otimização (% passível). O gasto reportado
  em US$ é só âncora, não entra no cálculo.
- Os 4 campos de token são INDEPENDENTES e aditivos (semântica de faturamento
  Anthropic/OpenAI: cache read/write são linhas à parte do input).
- Premissa: todo substituto sugerido existe na Databricks (on_databricks = true).
  * % alvo  = rebalancear tokens entre tiers; a fatia não-otimizada permanece no modelo
    do cliente (preço de lista AA do próprio modelo).
  * % passível = trocar por modelo de performance EQUIVALENTE, POR MODELO: cada modelo do
    cliente recebe UM substituto = o mais barato disponível na Databricks com intelligence
    >= a do PRÓPRIO modelo - tolerância. Dois modelos no mesmo tier têm recomendações
    independentes (podem coincidir, é questão dos dados).

A referência de modelo (`model_ref`) é injetada (lista de dicts vinda de v_model_ref):
match_key, slug_norm, model, provider, intelligence, price_input, price_output,
price_cache_read, price_cache_write, on_databricks.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Configuração (ajustável). Bandas de intelligence do índice AA (~0-65 nesta base).
# ---------------------------------------------------------------------------
TIERS = ("alta", "media", "baixa")
TIER_LABELS = {"alta": "Alta", "media": "Média", "baixa": "Baixa"}
ALTA_MIN = 50.0    # intelligence >= 50 -> Alta
MEDIA_MIN = 28.0   # 28 <= intelligence < 50 -> Média ; < 28 -> Baixa
# "performance equivalente": o substituto pode ter até EQUIV_TOLERANCE pontos de
# intelligence A MENOS que o modelo que está sendo substituído.
EQUIV_TOLERANCE = 3.0


def norm_slug(name: str) -> str:
    """match_key: mesma partição estável do SQL (v_aa_model_ref.match_key).

    Normaliza (LOWER + TRIM + '[ ._]+' -> '-'), quebra em tokens e reagrupa
    LETRAS (na ordem) ++ NÚMEROS (na ordem). Reconcilia a divergência de ORDEM de
    nome entre a AA e a Databricks (ex.: `claude-4-5-sonnet` <-> `claude-sonnet-4-5`)
    SEM colidir inversões de versão (`4-5` != `5-4`, ordem dos números preservada).
    Precisa ser idêntica à expressão SQL usada nas views.
    """
    s = re.sub(r"[ ._]+", "-", (name or "").strip().lower())
    toks = s.split("-")
    letters = "-".join(t for t in toks if not re.fullmatch(r"[0-9]+", t))
    numbers = "-".join(t for t in toks if re.fullmatch(r"[0-9]+", t))
    return "-".join(p for p in (letters, numbers) if p)


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


def _mix_total(mix: dict) -> float:
    return sum(mix.values())


def _scaled_mix(mix: dict, target_total: float) -> dict:
    """Reescala um mix mantendo as proporções para somar target_total tokens."""
    cur = _mix_total(mix)
    if cur <= 0:
        return _empty_mix()
    f = target_total / cur
    return {k: v * f for k, v in mix.items()}


def _pick_optimized_model(ref_by_slug: dict, model_intel: float | None, opt_mix: dict) -> dict | None:
    """Modelo mais barato, disponível na Databricks, de performance >= (modelo - tolerância)."""
    floor = (model_intel - EQUIV_TOLERANCE) if model_intel is not None else -1.0
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
    De-para POR MODELO: cada modelo do cliente recebe um substituto próprio.
    """
    ref_by_slug = {(r.get("match_key") or norm_slug(r.get("slug_norm", ""))): r for r in model_ref}

    warnings: list[str] = []
    reported_spend = 0.0
    baseline_cost = 0.0
    current_breakdown: list[dict] = []
    models_by_tier: dict[str, list[dict]] = {t: [] for t in TIERS}

    # --- 1) baseline: resolve + classifica + repreça cada modelo do cliente ---
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
        intel = rec.get("intelligence")
        t = tier_of(intel)
        label = rec.get("model") or name
        tokens = _mix_total(mix)
        models_by_tier[t].append({
            "label": label, "slug": slug, "tier": t, "mix": mix, "cost": cost,
            "tokens": tokens, "intel": (float(intel) if intel is not None else None),
        })
        current_breakdown.append({"model": label, "slug": slug, "tier": t,
                                  "tokens": tokens, "cost": cost})

    total_tokens = sum(m["tokens"] for ms in models_by_tier.values() for m in ms)
    if total_tokens <= 0:
        return {
            "baseline_cost": 0.0, "target_cost": 0.0, "savings": 0.0, "savings_pct": 0.0,
            "reported_spend": reported_spend, "total_tokens": 0.0, "warnings": warnings,
            "tiers": [], "current_breakdown": [], "target_breakdown": [],
        }

    # --- 2) cenário alvo: por modelo dentro de cada tier ---
    target_cost = 0.0
    tiers_out: list[dict] = []
    target_breakdown: list[dict] = []

    for t in TIERS:
        models = models_by_tier[t]
        cur_tokens = sum(m["tokens"] for m in models)
        cur_cost = sum(m["cost"] for m in models)
        b = budget.get(t, {}) or {}
        pct_atual = 100.0 * cur_tokens / total_tokens
        pct_alvo = float(b.get("pct_alvo", pct_atual))
        pct_opt = float(b.get("pct_optimizable", 0.0))
        target_tokens_tier = total_tokens * pct_alvo / 100.0
        # rebalanceamento: escala o volume do tier preservando a proporção entre modelos
        scale = (target_tokens_tier / cur_tokens) if cur_tokens > 0 else 0.0

        intel_num = sum((m["intel"] or 0.0) * m["tokens"] for m in models if m["intel"] is not None)
        intel_den = sum(m["tokens"] for m in models if m["intel"] is not None)
        tier_intel = (intel_num / intel_den) if intel_den else None

        tier_target_cost = 0.0
        models_detail: list[dict] = []
        for m in models:
            m_target = m["tokens"] * scale
            opt_tokens = m_target * pct_opt / 100.0
            non_opt_tokens = m_target - opt_tokens
            sub = None
            opt_cost = 0.0
            if opt_tokens > 0:
                opt_mix = _scaled_mix(m["mix"], opt_tokens)
                sub = _pick_optimized_model(ref_by_slug, m["intel"], opt_mix)
                if sub is None:
                    # sem alternativa disponível: mantém no próprio modelo
                    non_opt_tokens += opt_tokens
                    opt_tokens = 0.0
                else:
                    opt_cost = reprice(opt_mix, sub)
            # fatia não-otimizada: modelo do cliente a preço AA próprio (custo linear nos tokens)
            non_opt_cost = (m["cost"] * non_opt_tokens / m["tokens"]) if m["tokens"] > 0 else 0.0
            tier_target_cost += non_opt_cost + opt_cost

            if non_opt_tokens > 0:
                target_breakdown.append({"tier": t, "kind": "base", "tokens": non_opt_tokens,
                                         "cost": non_opt_cost, "model": m["label"]})
            if opt_tokens > 0 and sub:
                target_breakdown.append({"tier": t, "kind": "optimized", "tokens": opt_tokens,
                                         "cost": opt_cost, "model": sub.get("model"),
                                         "slug": sub.get("slug_norm"), "provider": sub.get("provider"),
                                         "intelligence": sub.get("intelligence")})
            models_detail.append({
                "model": m["label"], "slug": m["slug"], "intelligence": m["intel"],
                "current_tokens": m["tokens"],
                "substitute": ({"model": sub.get("model"), "provider": sub.get("provider"),
                                "intelligence": sub.get("intelligence"), "slug": sub.get("slug_norm")}
                               if (sub and opt_tokens > 0) else None),
            })

        target_cost += tier_target_cost
        tiers_out.append({
            "tier": t, "label": TIER_LABELS[t],
            "models": [m["label"] for m in models],
            "slugs": [m["slug"] for m in models],
            "intelligence": tier_intel,
            "pct_atual": round(pct_atual, 2), "pct_alvo": pct_alvo, "pct_optimizable": pct_opt,
            "current": {"tokens": cur_tokens, "cost": cur_cost},
            "target": {"tokens": target_tokens_tier, "cost": tier_target_cost},
            "models_detail": models_detail,
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
