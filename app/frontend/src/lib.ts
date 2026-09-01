// Tipos, formatação e cliente da API.

export type ModelRow = {
  model: string;
  input: number;
  output: number;
  cache_read: number;
  cache_write: number;
  spend_usd: number;
};

export type TierBudget = { pct_alvo: number; pct_optimizable: number };

export type OptimizedModel = {
  tokens: number; cost: number; model: string; slug?: string;
  provider?: string; intelligence?: number;
} | null;

export type TierResult = {
  tier: "alta" | "media" | "baixa";
  label: string;
  models: string[];
  slugs: string[];
  intelligence: number | null;
  pct_atual: number; pct_alvo: number; pct_optimizable: number;
  current: { tokens: number; cost: number };
  target: {
    tokens: number;
    non_optimized: { tokens: number; cost: number; model: string | null };
    optimized: OptimizedModel;
    cost: number;
  };
};

export type Segment = {
  tier: "alta" | "media" | "baixa";
  kind: "base" | "optimized";
  tokens: number; cost: number; model?: string;
  slug?: string; provider?: string; intelligence?: number;
};

export type CurrentSeg = { model: string; slug: string; tier: string; tokens: number; cost: number };

export type Result = {
  baseline_cost: number;
  target_cost: number;
  savings: number;
  savings_pct: number;
  reported_spend: number;
  total_tokens: number;
  warnings: string[];
  tiers: TierResult[];
  current_breakdown: CurrentSeg[];
  target_breakdown: Segment[];
  budget: Record<string, TierBudget>;
};

export type EstimateSummary = {
  id: string; created_at: string; title: string; provider: string;
  savings: number; savings_pct: number; baseline_cost: number;
};

export type ModelRef = {
  slug: string; model: string; provider: string; intelligence: number;
  tier: string; tier_label: string; on_databricks: boolean;
};

const TIER_COLORS: Record<string, string> = {
  alta: "var(--tier-alta)",
  media: "var(--tier-media)",
  baixa: "var(--tier-baixa)",
};
export const tierColor = (t: string) => TIER_COLORS[t] || "var(--tier-media)";
export const OPTIMIZED_COLOR = "var(--optimized)";

// -------- formatação --------
export function fmtUsd(v: number): string {
  const a = Math.abs(v);
  if (a >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
  if (a >= 10_000) return `$${(v / 1_000).toFixed(1)}k`;
  if (a >= 1) return `$${v.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  return `$${v.toFixed(2)}`;
}
export function fmtUsdFull(v: number): string {
  return `$${v.toLocaleString("en-US", { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`;
}
export function fmtTokens(v: number): string {
  const a = Math.abs(v);
  if (a >= 1_000_000_000) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1_000_000) return `${(v / 1e6).toFixed(1)}M`;
  if (a >= 1_000) return `${(v / 1e3).toFixed(1)}k`;
  return `${Math.round(v)}`;
}
export function fmtPct(v: number): string {
  return `${v.toFixed(v < 10 ? 1 : 0)}%`;
}

// -------- API --------
async function jfetch<T>(url: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(opts?.headers || {}) },
  });
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(`${res.status} ${txt}`);
  }
  return res.json();
}

export const api = {
  providers: () => jfetch<{ providers: string[] }>("/api/providers"),
  models: (provider?: string) =>
    jfetch<{ models: ModelRef[] }>(`/api/models${provider ? `?provider=${encodeURIComponent(provider)}` : ""}`),
  compute: (body: unknown) => jfetch<Result>("/api/estimate", { method: "POST", body: JSON.stringify(body) }),
  listEstimates: () => jfetch<{ estimates: EstimateSummary[] }>("/api/estimates"),
  getEstimate: (id: string) => jfetch<any>(`/api/estimates/${id}`),
  saveEstimate: (body: unknown) => jfetch<any>("/api/estimates", { method: "POST", body: JSON.stringify(body) }),
  deleteEstimate: (id: string) => jfetch<{ deleted: boolean }>(`/api/estimates/${id}`, { method: "DELETE" }),
  dashboardEmbed: () => jfetch<{ host: string; dashboard_id: string | null; embed_url: string | null; open_url: string }>("/api/dashboard-embed"),
};
