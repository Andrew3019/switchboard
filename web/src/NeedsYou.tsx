import { useState } from "react";
import { Link as QLink, Question, RepoState, State, ago, enc, post, safeUrl, span } from "./api";
import { Legend, TreeList } from "./Tree";
import { AgentActions } from "./Agent";

export function readerHref(repo: string, path: string, back: string): string {
  return `#/read?repo=${enc(repo)}&path=${enc(path)}&back=${enc(back)}`;
}

function LinkItem({ link, repo, back }: { link: QLink; repo: string; back: string }) {
  if (link.kind === "file") {
    const short = link.target.split("/").slice(-2).join("/");
    return (
      <a href={readerHref(repo, link.target, back)} className="file-link">
        {link.title || short} {link.title && <span className="mono small muted">{short}</span>}
      </a>
    );
  }
  const href = safeUrl(link.target);
  if (!href) return <span className="mono small">{link.target}</span>;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {link.title || href}
    </a>
  );
}

function QuestionCard({ q, repo, now }: { q: Question; repo: RepoState; now: number }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const p = q.parts || {};
  const back = `q-${repo.id}-${q.id}`;

  async function act(verb: "answer" | "resolve") {
    setBusy(true);
    const r = await post(`/api/q/${enc(repo.id)}/${q.id}/${verb}`, verb === "answer" ? { text } : {});
    setBusy(false);
    setMsg(r.ok ? { ok: true, text: verb === "answer" ? "Answer sent." : "Marked resolved." } : { ok: false, text: r.error || "failed" });
    if (r.ok) setText("");
  }

  return (
    <article className="card qcard" id={back}>
      <div className="qmain">
        <div className="meta">
          <span>asked by <span className="mono strong">{q.asker}</span></span>
          <span>·</span>
          <span>open {span(now - q.created_at)}</span>
          {q.escalated_at && (
            <span className="badge warn">escalated{q.escalated_from ? ` from ${q.escalated_from}` : ""}</span>
          )}
          <span className="mono small muted">question {q.id}</span>
        </div>
        <h3 className="decision">{q.body}</h3>

        {p.about && (
          <div className="field">
            <div className="lbl">What this is about</div>
            <p className="prose">{p.about}</p>
          </div>
        )}
        {p.catch_up && (
          <div className="field">
            <div className="lbl">Since you last replied to this agent · {ago(now, q.last_reply_at)}</div>
            <p className="prose">{p.catch_up}</p>
          </div>
        )}
        {!q.parts && (
          <p className="muted small">
            This question has no structured parts. The agent's own chat has the full message: use Focus in herdr or Transcript.
          </p>
        )}

        {p.options && p.options.length > 0 && (
          <div className="field">
            <div className="lbl">Pick one, or write your own below</div>
            <div className="opts">
              {p.options.map((o, i) => {
                const full = o.detail ? `${o.label}: ${o.detail}` : o.label;
                return (
                  <button
                    key={i}
                    className={`opt${o.recommended ? " rec" : ""}${text === full ? " picked" : ""}`}
                    onClick={() => setText(full)}
                  >
                    <span className="opt-label">{o.label}</span>
                    {o.recommended && <span className="opt-rec">Recommended</span>}
                    {o.detail && <span className="opt-detail">{o.detail}</span>}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {p.blocked && (
          <div className="inline-field">
            <span className="lbl">Blocked until you answer</span>
            <span>{p.blocked}</span>
          </div>
        )}

        {p.links && p.links.length > 0 && (
          <div className="field">
            <div className="lbl">Links</div>
            <div className="links">
              {p.links.map((l, i) => (
                <LinkItem key={i} link={l} repo={repo.id} back={back} />
              ))}
            </div>
          </div>
        )}

        <div className="field">
          <label className="lbl" htmlFor={`ans-${back}`}>Your answer</label>
          <textarea
            id={`ans-${back}`}
            rows={3}
            value={text}
            placeholder="Write as much as you need. New lines are fine."
            onChange={(e) => setText(e.target.value)}
          />
          <div className="row">
            <button className="btn primary" disabled={busy || !text.trim()} onClick={() => act("answer")}>
              Send answer
            </button>
            <button className="btn" disabled={busy} onClick={() => act("resolve")}>
              Mark resolved, no answer
            </button>
            <AgentActions repo={repo.id} name={q.asker} />
          </div>
          {msg && <div className={msg.ok ? "ok-msg" : "err-msg"}>{msg.text}</div>}
        </div>
      </div>
      <aside className="qtree" aria-label="Agent tree">
        <div className="lbl">Who is asking</div>
        <TreeList nodes={q.tree} highlight={q.asker} now={now} detail={false} />
        <Legend />
      </aside>
    </article>
  );
}

function Between({ q, repo, now }: { q: Question; repo: RepoState; now: number }) {
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <div className="side-item">
      <span className="prose small-prose">{q.body}</span>
      <span className="small muted">
        <span className="mono">{q.asker}</span> to <span className="mono">{q.target}</span> · {repo.name} · open {span(now - q.created_at)}
      </span>
      <div>
        <button
          className="btn small-btn"
          onClick={async () => {
            const r = await post(`/api/q/${enc(repo.id)}/${q.id}/escalate`);
            setMsg(r.ok ? "Now yours: it moves to the left on the next refresh." : r.error || "failed");
          }}
        >
          Take it myself
        </button>
      </div>
      {msg && <span className="small">{msg}</span>}
    </div>
  );
}

export function NeedsYou({ state, repos }: { state: State; repos: RepoState[] }) {
  const now = state.now;
  const asking = repos.filter((r) => r.questions.length);
  const prs = repos.flatMap((r) => r.prs.filter((p) => p.waiting_merge).map((p) => ({ p, r })));
  const stuck = repos.flatMap((r) => r.stuck.map((s) => ({ s, r })));
  const between = repos.flatMap((r) => r.between.map((q) => ({ q, r })));
  return (
    <main className="needs">
      <section className="qcol" aria-label="Questions for you">
        {asking.length === 0 && (
          <div className="empty">
            <h2>Nothing is waiting on you.</h2>
            <p className="muted">Questions agents ask you appear here within a couple of seconds.</p>
          </div>
        )}
        {asking.map((r) => {
          const tops = [...new Set(r.questions.map((q) => q.top))];
          return (
            <div key={r.id} className="repo-block">
              <div className="repo-head">
                <h2>{r.name}</h2>
                <span className="mono small muted">{r.checkout}</span>
              </div>
              {tops.map((top) => {
                const qs = r.questions.filter((q) => q.top === top);
                return (
                  <div key={top} className="tree-group">
                    <div className="tree-line">
                      <span className="lbl">Tree</span>
                      <span className="mono strong">{top}</span>
                      {qs[0].top_about && <span>· {qs[0].top_about}</span>}
                    </div>
                    {qs.map((q) => (
                      <QuestionCard key={q.id} q={q} repo={r} now={now} />
                    ))}
                  </div>
                );
              })}
            </div>
          );
        })}
      </section>

      <aside className="side" aria-label="Also worth a look">
        <div className="small muted">For visibility. Nothing here is waiting on an answer.</div>
        <section className="card side-card">
          <h2 className="lbl">PRs waiting on your merge</h2>
          {prs.length === 0 && <span className="small muted">None</span>}
          {prs.map(({ p, r }) => (
            <div key={`${r.id}-${p.number}`} className="side-item">
              <a href={safeUrl(p.url) || "#"} target="_blank" rel="noopener noreferrer" className="strong">
                {p.title}
              </a>
              <span className="small muted">
                {r.name} · {p.review}
                {p.checks ? ` · ${p.checks}` : ""}
              </span>
            </div>
          ))}
          {repos.filter((r) => r.pr_error).map((r) => (
            <span key={r.id} className="small err-msg">{r.name}: gh failed ({r.pr_error})</span>
          ))}
        </section>
        <section className="card side-card">
          <h2 className="lbl">Stuck or gone</h2>
          {stuck.length === 0 && <span className="small muted">None</span>}
          {stuck.map(({ s, r }) => (
            <div key={`${r.id}-${s.name}`} className="stuck">
              <span className="dot" style={{ background: s.gone ? "var(--red)" : "var(--orange)", marginTop: 6 }} />
              <div className="side-item">
                <span className="mono">{s.name}</span>
                <span className="small muted">
                  {r.name} · {s.gone ? "pane gone" : `stalled, idle ${span(s.idle || 0)}`}
                  {s.unread ? ` · ${s.unread} unread` : ""}
                </span>
              </div>
            </div>
          ))}
        </section>
        <section className="card side-card">
          <h2 className="lbl">Questions between agents</h2>
          {between.length === 0 && <span className="small muted">None</span>}
          {between.map(({ q, r }) => (
            <Between key={`${r.id}-${q.id}`} q={q} repo={r} now={now} />
          ))}
        </section>
      </aside>
    </main>
  );
}
