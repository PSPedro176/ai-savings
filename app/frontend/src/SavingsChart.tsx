import { useState } from "react";
import type { Result } from "./lib";
import { fmtUsd, fmtUsdFull, fmtTokens, fmtPct, tierColor, OPTIMIZED_COLOR } from "./lib";

type Metric = "tokens" | "cost";

// Geometria do SVG (escala via viewBox; largura fluida).
const W = 760, H = 470;
const TOP = 76, BOT = 44, PLOT = H - TOP - BOT;
const BARW = 104, LX = 150, RX = 506;

type Seg = {
  tier: "alta" | "media" | "baixa";
  kind: "base" | "optimized";
  label: string; value: number; tokens: number; cost: number;
  sub?: string;
};

export function SavingsChart({ result }: { result: Result }) {
  const [metric, setMetric] = useState<Metric>("tokens");
  const [hover, setHover] = useState<{ x: number; y: number; seg: Seg } | null>(null);

  const val = (tokens: number, cost: number) => (metric === "tokens" ? tokens : cost);

  const TIER_ORDER = { alta: 0, media: 1, baixa: 2 };
  const left: Seg[] = result.current_breakdown
    .map((s) => ({ tier: s.tier as Seg["tier"], kind: "base" as const, label: s.model, value: val(s.tokens, s.cost), tokens: s.tokens, cost: s.cost }))
    .sort((a, b) => TIER_ORDER[a.tier] - TIER_ORDER[b.tier]);
  const right: Seg[] = result.target_breakdown
    .map((s) => ({
      tier: s.tier, kind: s.kind, value: val(s.tokens, s.cost), tokens: s.tokens, cost: s.cost,
      label: s.kind === "optimized" ? (s.model || "Otimizado") : (s.model || "Base"),
      sub: s.kind === "optimized" ? `${s.provider || "OSS"}${s.intelligence ? ` · int. ${Math.round(s.intelligence)}` : ""}` : undefined,
    }))
    .sort((a, b) => TIER_ORDER[a.tier] - TIER_ORDER[b.tier] || (a.kind === "optimized" ? 1 : -1));

  const totalL = left.reduce((s, x) => s + x.value, 0) || 1;
  const totalR = right.reduce((s, x) => s + x.value, 0) || 1;
  const scaleMax = Math.max(totalL, totalR) || 1;
  const h = (v: number) => (v / scaleMax) * PLOT;

  // empilha (topo -> base) e registra extensão vertical por tier (p/ as fitas)
  function layout(segs: Seg[], x: number) {
    let y = TOP + (PLOT - h(segs.reduce((s, v) => s + v.value, 0)));
    const rects = segs.map((s) => {
      const height = h(s.value);
      const rect = { s, x, y, height };
      y += height;
      return rect;
    });
    const tierSpan: Record<string, { top: number; bot: number }> = {};
    rects.forEach((r) => {
      const t = tierSpan[r.s.tier] || { top: Infinity, bot: -Infinity };
      t.top = Math.min(t.top, r.y); t.bot = Math.max(t.bot, r.y + r.height);
      tierSpan[r.s.tier] = t;
    });
    return { rects, tierSpan };
  }
  const L = layout(left, LX);
  const R = layout(right, RX);

  const colColor = (s: Seg) => (s.kind === "optimized" ? OPTIMIZED_COLOR : tierColor(s.tier));

  const savingsPos = result.savings >= 0;

  return (
    <div className="chart-card panel">
      <div className="chart-top">
        <div>
          <div className="eyebrow">Economia potencial estimada</div>
          <h2 className="hero">
            <span className={savingsPos ? "hero-num pos" : "hero-num neg"}>{fmtUsd(Math.abs(result.savings))}</span>
            <span className="hero-tail">{savingsPos ? "de economia" : "a mais"} · {fmtPct(Math.abs(result.savings_pct))}</span>
          </h2>
          <div className="note">
            Comparado a {fmtUsdFull(result.baseline_cost)} no mix atual (preço de lista Artificial Analysis).
            {result.reported_spend > 0 && <> Gasto reportado hoje: {fmtUsdFull(result.reported_spend)}.</>}
          </div>
        </div>
        <div className="metric-toggle" role="tablist" aria-label="Métrica das barras">
          <button role="tab" aria-selected={metric === "tokens"} onClick={() => setMetric("tokens")}>Tokens</button>
          <button role="tab" aria-selected={metric === "cost"} onClick={() => setMetric("cost")}>US$</button>
        </div>
      </div>

      <div className="chart-plot" onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Comparação atual versus sugerido">
          {/* fitas ligando tiers (fluxo de consumo) */}
          {(["alta", "media", "baixa"] as const).map((t) => {
            const a = L.tierSpan[t], b = R.tierSpan[t];
            if (!a || !b) return null;
            const x1 = LX + BARW, x2 = RX;
            const c = (x1 + x2) / 2;
            const d = `M ${x1} ${a.top} C ${c} ${a.top}, ${c} ${b.top}, ${x2} ${b.top}
                       L ${x2} ${b.bot} C ${c} ${b.bot}, ${c} ${a.bot}, ${x1} ${a.bot} Z`;
            return <path key={t} d={d} fill={tierColor(t)} opacity={0.14} />;
          })}

          {/* colunas */}
          {[{ rects: L.rects, total: totalL, cost: result.baseline_cost, label: "Atual", x: LX },
            { rects: R.rects, total: totalR, cost: result.target_cost, label: "Sugerido", x: RX }].map((col) => (
            <g key={col.label}>
              {col.rects.map((r, i) => {
                const gap = r.height > 3 ? 2 : 0; // 2px de respiro entre segmentos
                return (
                  <rect
                    key={i} x={r.x} y={r.y + gap / 2} width={BARW} height={Math.max(0, r.height - gap)}
                    rx={3} fill={colColor(r.s)}
                    stroke={r.s.kind === "optimized" ? OPTIMIZED_COLOR : "none"}
                    onMouseMove={(e) => {
                      const box = (e.currentTarget.ownerSVGElement!.parentElement as HTMLElement).getBoundingClientRect();
                      setHover({ x: e.clientX - box.left, y: e.clientY - box.top, seg: r.s });
                    }}
                    style={{ cursor: "pointer" }}
                  />
                );
              })}
              {/* custo acima da coluna */}
              <text x={col.x + BARW / 2} y={TOP - 40} textAnchor="middle" className="col-cost">{fmtUsd(col.cost)}</text>
              <text x={col.x + BARW / 2} y={TOP - 22} textAnchor="middle" className="col-cost-sub">
                {metric === "tokens" ? fmtTokens(col.total) + " tokens" : "custo total"}
              </text>
              {/* rótulo da coluna */}
              <text x={col.x + BARW / 2} y={H - 16} textAnchor="middle" className="col-label">{col.label}</text>
            </g>
          ))}
        </svg>

        {hover && (
          <div className="chart-tip" style={{ left: hover.x, top: hover.y }}>
            <div className="tip-title">
              <span className="tier-dot" style={{ background: hover.seg.kind === "optimized" ? OPTIMIZED_COLOR : tierColor(hover.seg.tier) }} />
              {hover.seg.label}
            </div>
            {hover.seg.sub && <div className="tip-sub">{hover.seg.sub}</div>}
            <div className="tip-row"><span>Tier</span><b>{tierLabel(hover.seg.tier)}{hover.seg.kind === "optimized" ? " · otimizado" : ""}</b></div>
            <div className="tip-row"><span>Tokens</span><b>{fmtTokens(hover.seg.tokens)}</b></div>
            <div className="tip-row"><span>Custo</span><b>{fmtUsdFull(hover.seg.cost)}</b></div>
          </div>
        )}
      </div>

      <div className="chart-legend">
        {(["alta", "media", "baixa"] as const).map((t) => (
          <span className="leg" key={t}><span className="tier-dot" style={{ background: tierColor(t) }} />{tierLabel(t)}</span>
        ))}
        <span className="leg"><span className="tier-dot" style={{ background: OPTIMIZED_COLOR }} />Otimizado (OSS na Databricks)</span>
        <span className="spacer" />
        <span className="note">Valores são estimativas. Fonte: Artificial Analysis (preço de lista) + disponibilidade na Databricks.</span>
      </div>
    </div>
  );
}

function tierLabel(t: string) {
  return t === "alta" ? "Alta" : t === "media" ? "Média" : "Baixa";
}
