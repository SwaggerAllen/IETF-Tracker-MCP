import { useEffect, useState } from "react";

import {
  api,
  type Batch,
  type Cost,
  type Draft,
  type ThreadBrief,
  type ThreadDetail,
} from "./api";

type View = "threads" | "drafts" | "pipeline";

export default function App() {
  const [view, setView] = useState<View>("threads");
  return (
    <>
      <header>
        <h1>WG Activity Tracker — Debug UI</h1>
      </header>
      <nav>
        {(["threads", "drafts", "pipeline"] as View[]).map((v) => (
          <button
            key={v}
            className={view === v ? "active" : ""}
            onClick={() => setView(v)}
          >
            {v}
          </button>
        ))}
      </nav>
      <main>
        {view === "threads" && <ThreadsView />}
        {view === "drafts" && <DraftsView />}
        {view === "pipeline" && <PipelineView />}
      </main>
    </>
  );
}

function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): {
  data: T | null;
  error: string | null;
} {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    fn()
      .then((d) => live && setData(d))
      .catch((e: unknown) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, deps);
  return { data, error };
}

function ThreadsView() {
  const { data, error } = useAsync<ThreadBrief[]>(() => api.threads(), []);
  const [selected, setSelected] = useState<ThreadDetail | null>(null);

  if (error) return <p className="error">Failed to load threads: {error}</p>;
  if (!data) return <p>Loading…</p>;

  return (
    <div className="row">
      <div style={{ flex: 1 }}>
        {data.length === 0 && <p>No threads yet. Run ingestion + summarization.</p>}
        {data.map((t) => (
          <div className="card" key={t.thread_id}>
            <h3>{t.subject}</h3>
            <div className="meta">
              <span className="tag">{t.working_group}</span>
              <span className="tag">{t.status}</span>
              {t.consensus_state && <span className="tag">{t.consensus_state}</span>}
              {t.date_range}
            </div>
            <p>{t.summary_brief || "(not summarized)"}</p>
            <button className="action" onClick={() => void api.thread(t.thread_id).then(setSelected)}>
              detail
            </button>
            {t.archive_url && (
              <a href={t.archive_url} target="_blank" rel="noreferrer">
                source
              </a>
            )}
          </div>
        ))}
      </div>
      {selected && (
        <div style={{ flex: 1 }}>
          <div className="card">
            <h3>{selected.subject}</h3>
            <div className="meta">
              {selected.working_group} · {selected.status} ·{" "}
              {selected.consensus_state ?? "—"}
            </div>
            <p>{selected.summary ?? "(no summary)"}</p>
            {selected.key_positions.length > 0 && (
              <ul>
                {selected.key_positions.map((kp, i) => (
                  <li key={i}>
                    <strong>{kp.holder}</strong>: {kp.position} — {kp.context}
                  </li>
                ))}
              </ul>
            )}
            <div className="meta">Participants: {selected.participants.join(", ") || "—"}</div>
            {selected.drafts.length > 0 && (
              <div className="meta">
                Drafts:{" "}
                {selected.drafts.map((d) => `${d.draft_name} [${(d.versions_referenced ?? []).join(", ") || "?"}]`).join("; ")}
              </div>
            )}
            {selected.archive_url && (
              <p>
                <a href={selected.archive_url} target="_blank" rel="noreferrer">
                  open source thread
                </a>
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function DraftsView() {
  const { data, error } = useAsync<Draft[]>(() => api.drafts(), []);
  if (error) return <p className="error">Failed to load drafts: {error}</p>;
  if (!data) return <p>Loading…</p>;
  if (data.length === 0) return <p>No drafts referenced yet.</p>;
  return (
    <div>
      {data.map((d) => (
        <div className="card" key={d.draft_name}>
          <h3>{d.draft_name}</h3>
          <div className="meta">
            <span className="tag">{d.current_version ?? "?"}</span>
            <span className="tag">{d.thread_count} threads</span>
            {d.status ?? ""}
          </div>
          <p>{d.title ?? "(metadata not fetched)"}</p>
          {d.datatracker_url && (
            <a href={d.datatracker_url} target="_blank" rel="noreferrer">
              datatracker
            </a>
          )}
        </div>
      ))}
    </div>
  );
}

function PipelineView() {
  const [tick, setTick] = useState(0);
  const cost = useAsync<Cost>(() => api.cost(), [tick]);
  const batches = useAsync<Batch[]>(() => api.batches(), [tick]);
  const [message, setMessage] = useState<string | null>(null);

  async function retrigger(stage: string) {
    setMessage(`Dispatching ${stage}…`);
    const resp = await api.retrigger(stage);
    setMessage(resp.ok ? `Dispatched ${stage}.` : `Failed (${resp.status}). Is GitHub dispatch configured?`);
    setTick((n) => n + 1);
  }

  return (
    <div>
      <div className="card">
        <h3>Re-trigger pipeline</h3>
        {(["ingest", "poll", "recategorize"] as const).map((s) => (
          <button key={s} className="action" onClick={() => void retrigger(s)}>
            {s}
          </button>
        ))}
        {message && <p className="meta">{message}</p>}
      </div>
      <div className="card">
        <h3>Cost</h3>
        {cost.error && <p className="error">{cost.error}</p>}
        {cost.data && (
          <div className="meta">
            ${cost.data.total_usd.toFixed(4)} / ${cost.data.ceiling_usd.toFixed(2)} ceiling
            <ul>
              {Object.entries(cost.data.by_stage).map(([stage, amount]) => (
                <li key={stage}>
                  {stage}: ${amount.toFixed(4)}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <div className="card">
        <h3>Batch jobs</h3>
        {batches.data?.length === 0 && <p className="meta">No batches yet.</p>}
        {batches.data?.map((b) => (
          <div className="meta" key={b.id}>
            #{b.id} {b.stage} — {b.status} ({b.item_count} items)
          </div>
        ))}
      </div>
    </div>
  );
}
