import { useEffect, useState } from "react";
import { api } from "./lib";

export function Track() {
  const [embed, setEmbed] = useState<{ embed_url: string | null; open_url: string } | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    api.dashboardEmbed().then(setEmbed).catch(() => setFailed(true));
  }, []);

  return (
    <section className="track">
      <div className="section-head">
        <div>
          <div className="eyebrow">Acompanhar economia</div>
          <h1 className="page-title">Consumo real de IA</h1>
          <p className="lede">
            O painel abaixo é o dashboard AI/BI publicado no seu workspace — custo e tokens reais
            por modelo, harness e provider, direto das system tables.
          </p>
        </div>
        {embed?.open_url && (
          <a className="btn" href={embed.open_url} target="_blank" rel="noreferrer">Abrir no Databricks ↗</a>
        )}
      </div>

      {embed?.embed_url && !failed ? (
        <div className="embed-frame panel">
          <iframe
            title="AI Savings dashboard"
            src={embed.embed_url}
            onError={() => setFailed(true)}
            allow="clipboard-read; clipboard-write"
          />
        </div>
      ) : (
        <div className="embed-empty panel">
          <div className="embed-empty-inner">
            <h3>Dashboard não incorporado</h3>
            <p className="note">
              Para exibir aqui, habilite o domínio do app nos <b>approved domains</b> de embedding
              do workspace (Configurações → Segurança → Embedding de dashboards AI/BI).
            </p>
            {embed?.open_url && <a className="btn primary" href={embed.open_url} target="_blank" rel="noreferrer">Abrir dashboard no Databricks ↗</a>}
          </div>
        </div>
      )}
    </section>
  );
}
