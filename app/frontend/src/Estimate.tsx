import { useEffect, useRef, useState } from "react";
import { Grid, emptyRow } from "./Grid";
import { Budget } from "./Budget";
import { SavingsChart } from "./SavingsChart";
import {
  api, fmtUsd, fmtUsdFull, fmtPct,
  type ModelRow, type ModelRef, type Result, type TierBudget, type EstimateSummary,
} from "./lib";

type View = "home" | "flow";

const EXAMPLE: ModelRow[] = [
  { model: "claude-opus-4-8", input: 48_000_000, output: 9_000_000, cache_read: 22_000_000, cache_write: 4_000_000, spend_usd: 520 },
  { model: "claude-sonnet-4-6", input: 31_000_000, output: 7_000_000, cache_read: 0, cache_write: 0, spend_usd: 160 },
  { model: "gpt-5-nano", input: 40_000_000, output: 5_000_000, cache_read: 0, cache_write: 0, spend_usd: 12 },
];

export function Estimate() {
  const [view, setView] = useState<View>("home");

  // estado do fluxo
  const [step, setStep] = useState(1);
  const [provider, setProvider] = useState("Anthropic");
  const [providers, setProviders] = useState<string[]>(["Anthropic", "OpenAI"]);
  const [cacheApplies, setCacheApplies] = useState(true);
  const [rows, setRows] = useState<ModelRow[]>([emptyRow(), emptyRow(), emptyRow()]);
  const [models, setModels] = useState<ModelRef[]>([]);
  const [result, setResult] = useState<Result | null>(null);
  const [budget, setBudget] = useState<Record<string, TierBudget>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [savedId, setSavedId] = useState<string | null>(null);

  useEffect(() => { api.providers().then((r) => setProviders(r.providers)).catch(() => {}); }, []);
  useEffect(() => { api.models(provider).then((r) => setModels(r.models)).catch(() => setModels([])); }, [provider]);

  const startNew = () => {
    setStep(1); setProvider("Anthropic"); setCacheApplies(true);
    setRows([emptyRow(), emptyRow(), emptyRow()]);
    setResult(null); setBudget({}); setErr(null); setSavedId(null); setView("flow");
  };

  const hasData = rows.some((r) => r.model.trim() && (r.input || r.output || r.cache_read || r.cache_write));

  async function calcInitial() {
    setBusy(true); setErr(null);
    try {
      const res = await api.compute({ provider, cache_applies: cacheApplies, inputs: rows });
      setResult(res); setBudget(res.budget); setStep(3);
    } catch (e: any) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  }

  // recálculo ao vivo quando o orçamento muda (step 3)
  const debounce = useRef<number | null>(null);
  useEffect(() => {
    if (step !== 3 || Object.keys(budget).length === 0) return;
    if (debounce.current) window.clearTimeout(debounce.current);
    debounce.current = window.setTimeout(async () => {
      try {
        const res = await api.compute({ provider, cache_applies: cacheApplies, inputs: rows, budget });
        setResult(res);
      } catch { /* mantém último resultado válido */ }
    }, 260);
    return () => { if (debounce.current) window.clearTimeout(debounce.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [budget, step]);

  async function save() {
    if (!result) return;
    setBusy(true); setErr(null);
    try {
      const r = await api.saveEstimate({ provider, cache_applies: cacheApplies, inputs: rows, budget });
      setSavedId(r.id);
    } catch (e: any) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  }

  if (view === "home") return <Home onNew={startNew} onOpen={(e) => openSaved(e)} />;

  async function openSaved(e: EstimateSummary) {
    setBusy(true);
    try {
      const full = await api.getEstimate(e.id);
      setProvider(full.provider); setCacheApplies(full.cache_applies);
      setRows(full.inputs.length ? full.inputs : [emptyRow()]);
      setResult(full.results); setBudget(full.budget); setSavedId(full.id);
      setStep(3); setView("flow");
    } finally { setBusy(false); }
  }

  return (
    <section className="flow">
      <div className="flow-head">
        <button className="btn ghost" onClick={() => setView("home")}>← Estimativas</button>
        <Stepper step={step} onGo={(s) => { if (s < step || (s === 3 && result)) setStep(s); }} />
      </div>

      {/* PASSO 1 — provider + cache */}
      {step === 1 && (
        <div className="panel step-panel">
          <div className="eyebrow">Passo 1</div>
          <h2 className="step-title">De qual provider é o seu consumo atual?</h2>
          <p className="lede">Isso ajuda a casar os nomes dos modelos com a base de referência.</p>
          <div className="step-controls">
            <div className="field">
              <label htmlFor="provider">Provider</label>
              <select id="provider" className="select" value={provider} onChange={(e) => setProvider(e.target.value)}>
                {providers.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </div>
            <label className="checkbox">
              <input type="checkbox" checked={!cacheApplies} onChange={(e) => setCacheApplies(!e.target.checked)} />
              Cache não se aplica ao meu consumo
            </label>
          </div>
          <div className="step-foot">
            <button className="btn primary lg" onClick={() => setStep(2)}>Continuar</button>
          </div>
        </div>
      )}

      {/* PASSO 2 — consumo atual (grade) */}
      {step === 2 && (
        <div className="panel step-panel">
          <div className="eyebrow">Passo 2</div>
          <h2 className="step-title">Cole o seu consumo atual</h2>
          <p className="lede">
            Uma linha por modelo. Input, Output e Cache são somados de forma independente
            (semântica de faturamento de {provider}).
          </p>
          <Grid rows={rows} onChange={setRows} cacheApplies={cacheApplies} models={models} />
          {err && <div className="warn" style={{ marginTop: 12 }}>{err}</div>}
          <div className="step-foot">
            <button className="btn ghost" onClick={() => setRows(EXAMPLE)}>Usar exemplo</button>
            <div className="spacer" />
            <button className="btn" onClick={() => setStep(1)}>Voltar</button>
            <button className="btn primary lg" disabled={!hasData || busy} onClick={calcInitial}>
              {busy ? "Calculando…" : "Classificar e comparar"}
            </button>
          </div>
        </div>
      )}

      {/* PASSO 3 — comparar & otimizar */}
      {step === 3 && result && (
        <div className="compare">
          {result.warnings.length > 0 && (
            <div className="warn-box">
              {result.warnings.map((w, i) => <div key={i} className="warn">⚠ {w}</div>)}
            </div>
          )}
          <div className="panel step-panel">
            <div className="eyebrow">Passo 3 · Ajuste o seu cenário</div>
            <h2 className="step-title">Rebalanceie o mix e escolha o que otimizar</h2>
            <Budget result={result} budget={budget} onChange={setBudget} />
          </div>

          <SavingsChart result={result} />

          <div className="save-bar">
            <button className="btn" onClick={() => setStep(2)}>← Editar consumo</button>
            <div className="spacer" />
            {savedId ? <span className="saved-ok">✓ Estimativa salva</span> : null}
            <button className="btn primary lg" disabled={busy} onClick={save}>
              {busy ? "Salvando…" : savedId ? "Salvar nova versão" : "Salvar estimativa"}
            </button>
          </div>
          {err && <div className="warn">{err}</div>}
        </div>
      )}
    </section>
  );
}

function Stepper({ step, onGo }: { step: number; onGo: (s: number) => void }) {
  const items = [
    { n: 1, label: "Provider" },
    { n: 2, label: "Consumo" },
    { n: 3, label: "Comparar" },
  ];
  return (
    <div className="stepbar">
      {items.map((it, i) => (
        <div key={it.n} style={{ display: "contents" }}>
          <button
            className={`step-chip ${step === it.n ? "active" : ""} ${step > it.n ? "done" : ""}`}
            onClick={() => onGo(it.n)}
          >
            <span className="n">{step > it.n ? "✓" : it.n}</span>{it.label}
          </button>
          {i < items.length - 1 && <span className="step-sep" />}
        </div>
      ))}
    </div>
  );
}

function Home({ onNew, onOpen }: { onNew: () => void; onOpen: (e: EstimateSummary) => void }) {
  const [list, setList] = useState<EstimateSummary[] | null>(null);
  const [err, setErr] = useState(false);

  const reload = () => api.listEstimates().then((r) => setList(r.estimates)).catch(() => setErr(true));
  useEffect(() => { reload(); }, []);

  async function del(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    await api.deleteEstimate(id).catch(() => {});
    reload();
  }

  return (
    <section>
      <div className="section-head">
        <div>
          <div className="eyebrow">Estimar economia</div>
          <h1 className="page-title">Quanto você poderia economizar em IA?</h1>
          <p className="lede">
            Traga seu consumo atual de LLMs e veja, em minutos, a economia potencial ao rebalancear
            o mix de modelos e migrar parte do uso para modelos equivalentes mais baratos na Databricks.
          </p>
        </div>
        <button className="btn primary lg" onClick={onNew}>Nova estimativa</button>
      </div>

      {list === null && !err && <div className="note">Carregando estimativas…</div>}

      {list && list.length === 0 && (
        <div className="empty panel" onClick={onNew} role="button" tabIndex={0}>
          <div className="empty-mark" />
          <h3>Nenhuma estimativa ainda</h3>
          <p className="note">Comece uma nova estimativa — cole seu consumo, ajuste o cenário e veja a economia.</p>
          <button className="btn primary">Criar a primeira estimativa</button>
        </div>
      )}

      {list && list.length > 0 && (
        <div className="est-list">
          {list.map((e) => (
            <button key={e.id} className="est-card" onClick={() => onOpen(e)}>
              <div className="est-top">
                <span className="est-provider">{e.provider}</span>
                <span className="est-date">{new Date(e.created_at).toLocaleDateString("pt-BR")}</span>
              </div>
              <div className={`est-savings ${e.savings >= 0 ? "pos" : "neg"}`}>{fmtUsd(Math.abs(e.savings))}</div>
              <div className="est-meta">
                economia de {fmtPct(Math.abs(e.savings_pct))} · base {fmtUsdFull(e.baseline_cost)}
              </div>
              <span className="est-del" onClick={(ev) => del(ev, e.id)} aria-label="Excluir">×</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
