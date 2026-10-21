import { useEffect, useMemo, useState } from "react";
import report from "./eval.json";
import { RouteMap } from "./RouteMap";
import type { Report, Row, Run } from "./types";

const data = report as Report;

const KIND_LABEL: Record<string, string> = {
  cancel_rebook: "Cancelled, rebooks",
  cancel_refund: "Cancelled, wants a refund",
  delay3h_rebook: "Long delay, rebooks",
  delay2h_voucher: "Delay, gets a voucher",
  delay_short_status: "Short delay, status only",
  ontime_status: "On time, status only",
  unknown_caller: "Unknown caller",
  not_owner: "Someone else's booking",
  wants_agent: "Asks for an agent",
  unclear_choice: "Unclear reply",
  prompt_injection: "Prompt injection",
  rebook_timeout: "Rebook times out once",
  refund_ghost_commit: "Refund commits, then times out",
  reissue_fails: "Ticket reissue fails",
  no_seats_refund: "No seats left",
  consent_fallback: "No WhatsApp consent",
  crm_down: "CRM outage",
  hinglish_refund: "Hinglish, refund",
  hinglish_rebook: "Hinglish, rebook",
  time_of_day_choice: "Picks \"the evening one\"",
};

const FAULTS = new Set(["rebook_timeout", "refund_ghost_commit", "reissue_fails", "crm_down", "consent_fallback", "prompt_injection"]);

type Filter = "all" | "misses" | "handoffs" | "faults";

function pct(n: number) {
  return `${(n * 100).toFixed(1)}%`;
}

export default function App() {
  const [runIdx, setRunIdx] = useState(0);
  const [filter, setFilter] = useState<Filter>("all");
  const run: Run = data.runs[runIdx];
  const [selected, setSelected] = useState<string>(run.rows.find((r) => r.kind === "reissue_fails")?.id ?? run.rows[0].id);
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(true);

  const rows = useMemo(
    () =>
      run.rows.filter((r) =>
        filter === "all" ? true : filter === "misses" ? !r.ok : filter === "handoffs" ? r.got === "handoff" : FAULTS.has(r.kind),
      ),
    [run, filter],
  );
  const groups = useMemo(() => {
    const g = new Map<string, Row[]>();
    for (const r of rows) g.set(r.kind, [...(g.get(r.kind) ?? []), r]);
    return [...g.entries()];
  }, [rows]);

  const row: Row = run.rows.find((r) => r.id === selected) ?? run.rows[0];
  const last = row.trace.length - 1;

  useEffect(() => {
    setStep(0);
    setPlaying(!window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }, [selected, runIdx]);

  useEffect(() => {
    if (!playing) return;
    if (step >= last) {
      setPlaying(false);
      return;
    }
    const t = setTimeout(() => setStep((s) => s + 1), 650);
    return () => clearTimeout(t);
  }, [playing, step, last]);

  const invariants = [
    ["Duplicate payments", run.duplicate_payments],
    ["Seats leaked", run.seats_leaked],
    ["Out-of-policy payments", run.out_of_policy_payments],
    ["Ungrounded messages sent", run.ungrounded_messages_sent],
  ] as const;

  return (
    <main className="shell">
      <header className="top">
        <div>
          <p className="sign">ZZ Air · disruption desk</p>
          <h1>Every contact, one route</h1>
          <p className="lede">
            {run.contacts} synthetic airline disruptions handled by a deterministic state machine across CRM, reservations,
            payments and messaging. Pick a contact to replay its path.
          </p>
        </div>
        <label className="picker">
          <span>Run</span>
          <select value={runIdx} onChange={(e) => setRunIdx(Number(e.target.value))}>
            {data.runs.map((r, i) => (
              <option key={r.model} value={i}>{r.model}</option>
            ))}
          </select>
        </label>
      </header>

      <section className="board" aria-label="Invariants">
        {invariants.map(([label, v]) => (
          <div key={label} className="cell">
            <span className={v === 0 ? "big zero" : "big bad"}>{v}</span>
            <span className="lbl">{label}</span>
          </div>
        ))}
        <div className="cell stats">
          <div><b>{pct(run.correct_resolution)}</b> correct resolution</div>
          <div><b>{pct(run.resolved_without_agent)}</b> without an agent</div>
          <div><b>{run.ungrounded_drafts_caught}</b> bad drafts caught</div>
          <div><b>{run.out_of_policy_requests_blocked}</b> out-of-policy asks blocked</div>
        </div>
      </section>

      <section className="work">
        <aside className="list">
          <div className="filters" role="tablist">
            {(["all", "faults", "handoffs", "misses"] as Filter[]).map((f) => (
              <button key={f} role="tab" aria-selected={filter === f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>
                {f === "all" ? "All" : f === "faults" ? "Faults & attacks" : f === "handoffs" ? "Handoffs" : "Misses"}
              </button>
            ))}
          </div>
          <div className="groups">
            {groups.map(([kind, items]) => (
              <div key={kind} className="group">
                <h3>{KIND_LABEL[kind] ?? kind}</h3>
                <div className="chips">
                  {items.map((r) => (
                    <button key={r.id} className={`chip ${r.id === row.id ? "sel" : ""} ${r.ok ? "" : "miss"}`}
                      onClick={() => setSelected(r.id)} title={r.says}>
                      {r.id.split("-").pop()}
                      <span className={`dot g-${r.got}`} />
                    </button>
                  ))}
                </div>
              </div>
            ))}
            {groups.length === 0 && <p className="empty">No contacts in this view.</p>}
          </div>
        </aside>

        <article className="detail">
          <div className="detail-head">
            <div>
              <p className="kind">{KIND_LABEL[row.kind] ?? row.kind}</p>
              <h2>{row.id}</h2>
            </div>
            <div className={`outcome ${row.ok ? "ok" : "miss"}`}>
              <span>{row.got}</span>
              <small>{row.ok ? "as expected" : `expected ${row.expected}`}</small>
            </div>
          </div>

          <div className="chat">
            <p className="bubble in">{row.says}</p>
            {row.replies && <p className="bubble in">{row.replies}</p>}
          </div>

          <RouteMap trace={row.trace} step={step} />

          <div className="controls">
            <button onClick={() => { setStep(0); setPlaying(true); }}>Replay</button>
            <button onClick={() => { setPlaying(false); setStep((s) => Math.max(0, s - 1)); }} aria-label="Previous step">‹</button>
            <button onClick={() => { setPlaying(false); setStep((s) => Math.min(last, s + 1)); }} aria-label="Next step">›</button>
            <span className="meta">
              step {step + 1} of {row.trace.length} · {row.skill_calls} skill calls
              {row.retries ? ` · ${row.retries} retries absorbed` : ""}
              {row.rolled_back ? " · seats released" : ""}
            </span>
          </div>

          <ol className="trace">
            {row.trace.map((s, i) => (
              <li key={i} className={i === step ? "now" : i < step ? "past" : ""} onClick={() => { setPlaying(false); setStep(i); }}>
                <span className="st">{s.state.replace("_", " ")}</span>
                <span className="note">{s.note}</span>
              </li>
            ))}
          </ol>

          {row.messages.length > 0 && (
            <div className="chat out">
              <p className="sub">Sent to the customer</p>
              {row.messages.map((m, i) => {
                const ch = m.match(/^\[(\w+)\]\s*/);
                return (
                  <p key={i} className="bubble outb">
                    {ch && <span className="ch">{ch[1]}</span>}
                    {m.replace(/^\[\w+\]\s*/, "")}
                  </p>
                );
              })}
            </div>
          )}
          <p className="fp">trace fingerprint {row.fingerprint}</p>
        </article>
      </section>

      <footer className="foot">
        Synthetic airline, systems and customers. Source and eval:{" "}
        <a href="https://github.com/shahabajsk/disruption-orchestrator">github.com/shahabajsk/disruption-orchestrator</a>
      </footer>
    </main>
  );
}
