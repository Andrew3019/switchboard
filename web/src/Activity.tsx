import { useEffect, useState } from "react";
import { PR, RepoState, State, Tree, enc, post, safeUrl, span } from "./api";
import { TreeList, dotColor } from "./Tree";
import { MessageBox } from "./Agent";

type Preview = {
  ok: boolean;
  error: string | null;
  closing: string[];
  questions: { id: number; asker: string; target: string; body: string }[];
  work: { worktree: string; uncommitted: number; unpushed: number }[];
  steps: { plan: string; step: string; owner: string; progress: string; title: string | null }[];
  prs: PR[];
};

const NO_PREVIEW: Preview = { ok: false, error: null, closing: [], questions: [], work: [], steps: [], prs: [] };

function PrLine({ p }: { p: PR }) {
  return (
    <div className="pr">
      <a href={safeUrl(p.url) || "#"} target="_blank" rel="noopener noreferrer" className="strong">
        {p.title}
      </a>
      <span className="small muted">
        {p.draft ? "draft" : "open"} · {p.review}
        {p.checks ? ` · ${p.checks}` : ""}
        {p.waiting_merge ? " · waiting on your merge" : ""}
      </span>
    </div>
  );
}

function CloseConfirm({ repo, tree, onCancel }: { repo: string; tree: Tree; onCancel: () => void }) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => {
    post(`/api/tree/${enc(repo)}/${enc(tree.top)}/preview`).then((r) =>
      setPreview({ ...NO_PREVIEW, ...(r as Partial<Preview>) }),
    );
  }, [repo, tree.top]);
  if (!preview) return <div className="confirm">Checking what closing would take with it…</div>;
  const others = Math.max(0, preview.closing.length - 1);
  return (
    <div role="region" aria-label="Confirm closing this tree" className="confirm">
      <div className="strong">
        Close {tree.top}
        {others ? ` and the ${others} agent${others > 1 ? "s" : ""} under it` : ""}?
      </div>
      {!preview.ok && <div className="err-msg">The dry run failed: {preview.error}</div>}
      <ul>
        {preview.questions.length > 0 && (
          <li>
            Withdraws {preview.questions.length} open question{preview.questions.length > 1 ? "s" : ""}:{" "}
            {preview.questions.map((q) => `"${q.body}"`).join(", ")}
          </li>
        )}
        <li>
          Closes {preview.closing.length} agent pane{preview.closing.length === 1 ? "" : "s"}
          {preview.closing.length ? `: ${preview.closing.join(", ")}` : ""}. Their transcripts stay, and sb restore can bring them back.
        </li>
        {preview.prs.map((p) => (
          <li key={p.number} className="warn-text">
            The PR "{p.title}" is still open. Closing does not merge or close it.
          </li>
        ))}
        {preview.work.map((w) => (
          <li key={w.worktree} className="warn-text">
            {w.worktree}: {w.uncommitted ? `${w.uncommitted} uncommitted change${w.uncommitted > 1 ? "s" : ""}` : ""}
            {w.uncommitted && w.unpushed ? ", " : ""}
            {w.unpushed ? `${w.unpushed} commit${w.unpushed > 1 ? "s" : ""} not pushed` : ""}
          </li>
        ))}
        {preview.steps.map((s) => (
          <li key={`${s.plan}-${s.step}`} className="warn-text">
            Plan step {s.title || s.step} ({s.plan}) owned by {s.owner} is {s.progress}, not complete.
          </li>
        ))}
      </ul>
      {result && <div className={result.ok ? "ok-msg" : "err-msg"}>{result.text}</div>}
      <div className="row">
        <button
          className="btn danger-solid"
          disabled={busy || !!result?.ok}
          onClick={async () => {
            setBusy(true);
            const r = await post(`/api/tree/${enc(repo)}/${enc(tree.top)}/close`);
            setBusy(false);
            setResult(r.ok ? { ok: true, text: "Closed." } : { ok: false, text: r.error || "close failed" });
          }}
        >
          {busy ? "Closing… this can take a while" : "Close tree"}
        </button>
        <button className="btn" onClick={onCancel}>{result?.ok ? "Done" : "Cancel"}</button>
      </div>
    </div>
  );
}

function TreeCard({ repo, tree, now, go }: { repo: RepoState; tree: Tree; now: number; go: (h: string) => void }) {
  const [mode, setMode] = useState<"none" | "message" | "close">("none");
  const [focusMsg, setFocusMsg] = useState<string | null>(null);
  const top = tree.nodes[0];
  return (
    <article className="card tcard">
      <div className="tree" aria-label="Agent tree">
        <div className="lbl">Tree</div>
        <TreeList nodes={tree.nodes} now={now} detail={true} />
      </div>
      <div className="info">
        <div className="row baseline">
          <h3 className="ttitle">{tree.about || tree.top}</h3>
          {tree.needs_you > 0 ? (
            <a href="#/needs" className="pill amber" onClick={() => go("#/needs")}>
              Needs you · {tree.needs_you}
            </a>
          ) : (
            <span className="pill" style={{ color: dotColor(top) }}>
              {top.finished ? "Done" : top.gone ? "Gone" : top.display || top.derived || top.state}
            </span>
          )}
          <span className="small muted">
            running {span(now - tree.created_at)} · {tree.nodes.length} agent{tree.nodes.length > 1 ? "s" : ""}
          </span>
        </div>
        {tree.about && <div className="mono small muted">{tree.top}</div>}
        {tree.latest_report && (
          <div className="field">
            <div className="lbl">Latest report</div>
            <p className="prose small-prose">
              <span className="mono">{tree.latest_report.agent}</span>: {tree.latest_report.text}
            </p>
          </div>
        )}
        <div className="field">
          <div className="lbl">Pull requests</div>
          {tree.prs.length === 0 ? <span className="small muted">None yet</span> : tree.prs.map((p) => <PrLine key={p.number} p={p} />)}
        </div>
        {mode === "message" && <MessageBox repo={repo.id} name={tree.top} onDone={() => setMode("none")} />}
        {mode === "close" && <CloseConfirm repo={repo.id} tree={tree} onCancel={() => setMode("none")} />}
        <div className="row">
          <button
            className="btn"
            title="Moves focus inside herdr. It cannot bring the terminal window to the front."
            onClick={async () => {
              const r = await post(`/api/agent/${enc(repo.id)}/${enc(tree.top)}/focus`);
              setFocusMsg(r.ok ? "Focused in herdr." : r.error || "focus failed");
            }}
          >
            Focus in herdr
          </button>
          <button className="btn" onClick={() => setMode(mode === "message" ? "none" : "message")}>Message</button>
          {mode !== "close" && (
            <button className="btn danger push-left" onClick={() => setMode("close")}>Close tree</button>
          )}
        </div>
        {focusMsg && <div className="small muted">{focusMsg}</div>}
      </div>
    </article>
  );
}

export function Activity({ state, repos, go }: { state: State; repos: RepoState[]; go: (h: string) => void }) {
  const shown = repos.filter((r) => r.trees.length || r.error || r.status_error);
  return (
    <main className="activity">
      {shown.length === 0 && (
        <div className="empty">
          <h2>No agents are running.</h2>
        </div>
      )}
      {shown.map((r) => (
        <section key={r.id} className="repo-block">
          <div className="repo-head">
            <h2>{r.name}</h2>
            <span className="small muted">
              {r.trees.length} tree{r.trees.length === 1 ? "" : "s"} under the dispatcher
            </span>
          </div>
          {r.error && <div className="err-msg">Cannot read this repo's store: {r.error}</div>}
          {r.status_error && <div className="err-msg">sb status failed here: {r.status_error}</div>}
          {r.trees.map((t) => (
            <TreeCard key={t.top} repo={r} tree={t} now={state.now} go={go} />
          ))}
        </section>
      ))}
    </main>
  );
}
