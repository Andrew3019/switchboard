import { useEffect, useState } from "react";
import { State, getJSON } from "./api";
import { NeedsYou } from "./NeedsYou";
import { Activity } from "./Activity";
import { Reader } from "./Reader";

const POLL_MS = 2000;

function route(): { view: string; params: URLSearchParams } {
  const h = window.location.hash.replace(/^#\/?/, "");
  const [view, query] = h.split("?");
  return { view: view || "needs", params: new URLSearchParams(query || "") };
}

export function App() {
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fetchedAt, setFetchedAt] = useState(0);
  const [tick, setTick] = useState(Date.now());
  const [where, setWhere] = useState(route());
  const [repo, setRepo] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      getJSON<State>("/api/state").then(
        (s) => {
          if (!alive) return;
          setState(s);
          setError(null);
          setFetchedAt(Date.now());
        },
        (e) => alive && setError(e.message),
      );
    load();
    const t = setInterval(load, POLL_MS);
    const c = setInterval(() => setTick(Date.now()), 1000);
    const onHash = () => setWhere(route());
    window.addEventListener("hashchange", onHash);
    return () => {
      alive = false;
      clearInterval(t);
      clearInterval(c);
      window.removeEventListener("hashchange", onHash);
    };
  }, []);

  const at = where.params.get("at");
  useEffect(() => {
    if (where.view === "needs" && at && state) document.getElementById(at)?.scrollIntoView({ block: "start" });
  }, [where.view, at, state !== null]);

  const go = (h: string) => {
    window.location.hash = h;
  };
  const all = state?.repos ?? [];
  const repos = repo ? all.filter((r) => r.id === repo) : all;
  const asking = all.reduce((n, r) => n + r.questions.length, 0);
  const updated = fetchedAt ? Math.round((tick - fetchedAt) / 1000) : null;

  return (
    <div className="page">
      <header className="top">
        <div className="top-inner">
          <div className="brand">
            <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" fill="none" stroke="#E8A33C" strokeWidth="2">
              <circle cx="4" cy="4" r="2.5" />
              <circle cx="14" cy="9" r="2.5" />
              <circle cx="4" cy="14" r="2.5" />
              <path d="M6.5 4.5 11.5 8.5M6.5 13.5l5-4" />
            </svg>
            switchboard
          </div>
          <nav aria-label="Views" className="views">
            <a href="#/needs" className={where.view === "needs" ? "on" : ""}>
              Needs you <span className="count mono">{asking}</span>
            </a>
            <a href="#/activity" className={where.view === "activity" ? "on" : ""}>Activity</a>
          </nav>
          <div className="repos" aria-label="Repos">
            <button className={repo === null ? "on" : ""} onClick={() => setRepo(null)}>All repos</button>
            {all.map((r) => (
              <button key={r.id} className={repo === r.id ? "on" : ""} onClick={() => setRepo(r.id)}>
                {r.name} · {r.questions.length}
              </button>
            ))}
          </div>
          <div className="mono stamp">
            {window.location.host}
            {updated !== null && ` · updated ${updated}s ago`}
          </div>
        </div>
      </header>
      {error && <div className="banner">Cannot reach sb web: {error}</div>}
      {!state && !error && <main className="empty">Loading…</main>}
      {state && where.view === "needs" && <NeedsYou state={state} repos={repos} />}
      {state && where.view === "activity" && <Activity state={state} repos={repos} go={go} />}
      {state && where.view === "read" && (
        <Reader
          repo={where.params.get("repo") || ""}
          path={where.params.get("path") || ""}
          back={where.params.get("back") || ""}
          now={state.now}
        />
      )}
    </div>
  );
}
