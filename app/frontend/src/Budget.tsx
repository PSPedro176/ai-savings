import type { Result, TierBudget } from "./lib";
import { fmtPct, tierColor, OPTIMIZED_COLOR } from "./lib";

type Props = {
  result: Result;
  budget: Record<string, TierBudget>;
  onChange: (b: Record<string, TierBudget>) => void;
};

export function Budget({ result, budget, onChange }: Props) {
  const tiers = result.tiers.filter((t) => t.current.tokens > 0);
  const sumAlvo = tiers.reduce((s, t) => s + (budget[t.tier]?.pct_alvo ?? t.pct_atual), 0);
  const sumOk = Math.abs(sumAlvo - 100) < 0.5;

  const set = (tier: string, key: keyof TierBudget, v: number) => {
    const cur = budget[tier] || { pct_alvo: 0, pct_optimizable: 0 };
    onChange({ ...budget, [tier]: { ...cur, [key]: v } });
  };

  return (
    <div className="budget">
      <div className="budget-grid">
        <div className="bhead">Performance</div>
        <div className="bhead">Modelos atuais</div>
        <div className="bhead bnum">% atual</div>
        <div className="bhead bnum">% alvo</div>
        <div className="bhead bnum">% otimizável (OSS)</div>
        <div className="bhead">Substituto na Databricks</div>

        {tiers.map((t) => {
          const b = budget[t.tier] || { pct_alvo: t.pct_atual, pct_optimizable: 0 };
          const subs = t.models_detail.filter((m) => m.substitute);
          return (
            <div className="brow" key={t.tier} style={{ display: "contents" }}>
              <div className="bcell btier">
                <span className="tier-dot" style={{ background: tierColor(t.tier) }} />
                <span className="tier-name">{t.label}</span>
                {t.intelligence != null && <span className="tier-intel">int. {t.intelligence.toFixed(0)}</span>}
              </div>
              <div className="bcell bmodels">{t.models.join(", ") || "—"}</div>
              <div className="bcell bnum bstatic">{fmtPct(t.pct_atual)}</div>
              <div className="bcell bnum">
                <PctInput value={b.pct_alvo} onChange={(v) => set(t.tier, "pct_alvo", v)} />
              </div>
              <div className="bcell bnum">
                <PctInput value={b.pct_optimizable} onChange={(v) => set(t.tier, "pct_optimizable", v)} accent />
              </div>
              <div className="bcell bsub">
                {b.pct_optimizable > 0 && subs.length > 0 ? (
                  <div className="sub-list">
                    {subs.map((m) => (
                      <span className="sub-pill" key={m.slug} style={{ borderColor: OPTIMIZED_COLOR }}>
                        <span className="tier-dot" style={{ background: OPTIMIZED_COLOR }} />
                        {m.model} → {m.substitute!.model}{m.substitute!.provider ? ` · ${m.substitute!.provider}` : ""}
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="note">—</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="budget-foot">
        <div className={`sum-badge ${sumOk ? "ok" : "bad"}`}>
          Soma % alvo: <b>{sumAlvo.toFixed(0)}%</b>{!sumOk && " (precisa somar 100%)"}
        </div>
        <span className="note">
          <b>% alvo</b> rebalanceia o mix entre tiers · <b>% otimizável</b> troca por um modelo
          equivalente mais barato disponível na Databricks.
        </span>
      </div>
    </div>
  );
}

function PctInput({ value, onChange, accent }: { value: number; onChange: (v: number) => void; accent?: boolean }) {
  return (
    <div className={`pct-input ${accent ? "accent" : ""}`}>
      <input
        type="number" min={0} max={100} step={1}
        value={Number.isFinite(value) ? Math.round(value) : 0}
        onChange={(e) => onChange(Math.max(0, Math.min(100, Number(e.target.value) || 0)))}
        onFocus={(e) => e.target.select()}
      />
      <span>%</span>
    </div>
  );
}
