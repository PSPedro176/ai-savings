import { useRef } from "react";
import type { ModelRow, ModelRef } from "./lib";

// Colunas da grade. `num` marca colunas numéricas. `hint` = tooltip com a convenção.
const COLS: { key: keyof ModelRow; label: string; num: boolean; cache?: boolean; hint?: string }[] = [
  { key: "model", label: "Modelo", num: false },
  { key: "input", label: "Input", num: true, hint: "Tokens de entrada SEM cache (cache read/write são colunas à parte, somadas)." },
  { key: "output", label: "Output", num: true },
  { key: "cache_read", label: "Cache read", num: true, cache: true, hint: "Tokens lidos do cache — aditivo ao input (convenção Anthropic/OpenAI)." },
  { key: "cache_write", label: "Cache write", num: true, cache: true, hint: "Tokens de escrita/criação de cache — aditivo ao input." },
  { key: "spend_usd", label: "Valor gasto (US$)", num: true, hint: "Âncora informativa: não entra no cálculo (o custo é reprecificado a preço de lista AA)." },
];

export function emptyRow(): ModelRow {
  return { model: "", input: 0, output: 0, cache_read: 0, cache_write: 0, spend_usd: 0 };
}

// Parse tolerante (formato en-US): "1,234,567" -> 1234567 ; "1.2M" ; "800k" ; "$3.50".
// Vírgula = separador de milhar (removida); ponto = decimal.
function parseNum(raw: string): number {
  let s = (raw || "").trim().toLowerCase().replace(/us\$|\$|\s/g, "");
  if (!s) return 0;
  const suf = s.match(/([kmb])$/);
  const mult = suf ? (suf[1] === "k" ? 1e3 : suf[1] === "m" ? 1e6 : 1e9) : 1;
  if (suf) s = s.slice(0, -1);
  const n = Number(s.replace(/,/g, "").replace(/[^\d.-]/g, ""));
  return (isNaN(n) ? 0 : n) * mult;
}

type Props = {
  rows: ModelRow[];
  onChange: (rows: ModelRow[]) => void;
  cacheApplies: boolean;
  models: ModelRef[];
};

export function Grid({ rows, onChange, cacheApplies, models }: Props) {
  const cols = COLS.filter((c) => !c.cache || cacheApplies);
  const gridRef = useRef<HTMLDivElement>(null);
  // sinal de convenção errada: input COM cache embutido (estilo gateway) contaria em dobro
  const cacheDoubleCount = cacheApplies && rows.some((r) => r.input > 0 && r.cache_read + r.cache_write > r.input);

  const setCell = (r: number, key: keyof ModelRow, value: string) => {
    const next = rows.map((row) => ({ ...row }));
    if (key === "model") next[r].model = value;
    else (next[r][key] as number) = parseNum(value);
    onChange(next);
  };

  // Colar planilha: distribui a partir da célula (r0,c0). Expande linhas conforme necessário.
  const onPaste = (e: React.ClipboardEvent, r0: number, c0: number) => {
    const text = e.clipboardData.getData("text");
    if (!text || (!text.includes("\t") && !text.includes("\n"))) return; // valor único: comportamento padrão
    e.preventDefault();
    const matrix = text
      .replace(/\r/g, "")
      .split("\n")
      .filter((l, i, arr) => l.length > 0 || i < arr.length - 1)
      .map((line) => (line.includes("\t") ? line.split("\t") : line.split(/,(?=(?:[^"]*"[^"]*")*[^"]*$)/)));
    while (matrix.length && matrix[matrix.length - 1].every((c) => c.trim() === "")) matrix.pop();

    const next = rows.map((row) => ({ ...row }));
    matrix.forEach((line, ri) => {
      const r = r0 + ri;
      while (next.length <= r) next.push(emptyRow());
      line.forEach((cell, ci) => {
        const col = cols[c0 + ci];
        if (!col) return;
        if (col.key === "model") next[r].model = cell.trim();
        else (next[r][col.key] as number) = parseNum(cell);
      });
    });
    onChange(next);
  };

  const addRow = () => onChange([...rows, emptyRow()]);
  const removeRow = (r: number) => onChange(rows.length > 1 ? rows.filter((_, i) => i !== r) : [emptyRow()]);
  const clearAll = () => onChange([emptyRow(), emptyRow(), emptyRow()]);

  return (
    <div className="grid-wrap" ref={gridRef}>
      <div className="grid" style={{ gridTemplateColumns: `1.6fr repeat(${cols.length - 1}, 1fr) 34px` }}>
        {cols.map((c) => (
          <div key={c.key} className={`gcell ghead ${c.num ? "gnum" : ""}`} title={c.hint}>{c.label}</div>
        ))}
        <div className="gcell ghead" />
        {rows.map((row, r) =>
          <RowCells
            key={r}
            row={row} r={r} cols={cols}
            onCell={setCell} onPaste={onPaste} onRemove={() => removeRow(r)}
          />
        )}
      </div>
      <datalist id="model-suggestions">
        {models.map((m) => <option key={m.slug} value={m.model} />)}
      </datalist>
      <div className="grid-actions">
        <button className="btn ghost" onClick={addRow}>+ Linha</button>
        <button className="btn ghost" onClick={clearAll}>Limpar</button>
        <span className="note">Dica: cole (Ctrl+V / Cmd+V) direto de uma planilha para preencher várias linhas.</span>
      </div>
      <p className="note grid-conv">
        Convenção: <b>Input</b> é a entrada <b>sem</b> cache; <b>cache read/write</b> entram à parte (somados),
        como na fatura da Anthropic/OpenAI — não cole números do gateway (que já embutem cache no input).
      </p>
      {cacheDoubleCount && (
        <p className="note" style={{ color: "#b4232c" }}>
          Atenção: em alguma linha o cache excede o input — confira se não colou o input <b>com</b> cache
          embutido (isso contaria os tokens de cache em dobro).
        </p>
      )}
    </div>
  );
}

function RowCells({ row, r, cols, onCell, onPaste, onRemove }: {
  row: ModelRow; r: number; cols: typeof COLS;
  onCell: (r: number, key: keyof ModelRow, v: string) => void;
  onPaste: (e: React.ClipboardEvent, r: number, c: number) => void;
  onRemove: () => void;
}) {
  return (
    <>
      {cols.map((c, ci) => (
        <div key={c.key} className={`gcell ${c.num ? "gnum" : ""}`}>
          <input
            className="gin"
            list={c.key === "model" ? "model-suggestions" : undefined}
            inputMode={c.num ? "decimal" : "text"}
            value={c.key === "model" ? row.model : displayNum(row[c.key] as number)}
            placeholder={c.key === "model" ? "ex.: claude-opus-4-8" : "0"}
            onChange={(e) => onCell(r, c.key, e.target.value)}
            onPaste={(e) => onPaste(e, r, ci)}
            onFocus={(e) => e.target.select()}
          />
        </div>
      ))}
      <div className="gcell gtrash">
        <button className="row-x" onClick={onRemove} aria-label={`Remover linha ${r + 1}`}>×</button>
      </div>
    </>
  );
}

function displayNum(n: number): string {
  if (!n) return "";
  return n.toLocaleString("en-US");
}
