import { useState } from "react";
import { Estimate } from "./Estimate";
import { Track } from "./Track";

type Tab = "estimate" | "track";

export function App() {
  const [tab, setTab] = useState<Tab>("estimate");
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="mark" />
          <span className="name">AI Savings</span>
          <span className="sub">Databricks</span>
        </div>
        <div className="spacer" />
        <nav className="tabs" role="tablist" aria-label="Seções">
          <button role="tab" aria-selected={tab === "estimate"} onClick={() => setTab("estimate")}>
            Estimar economia
          </button>
          <button role="tab" aria-selected={tab === "track"} onClick={() => setTab("track")}>
            Acompanhar economia
          </button>
        </nav>
      </header>
      <main className="main">
        {tab === "estimate" ? <Estimate /> : <Track />}
      </main>
    </div>
  );
}
