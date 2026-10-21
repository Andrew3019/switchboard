import { Node, ago, span } from "./api";

export function dotColor(n: Node): string {
  if (n.question?.target === "human") return "var(--amber)";
  if (n.finished) return "var(--grey)";
  if (n.gone || n.derived === "stalled") return "var(--red)";
  return "var(--green)";
}

export function say(n: Node, now: number): string {
  if (n.question) {
    return n.question.target === "human"
      ? `Waiting on you: ${n.question.body}`
      : `Waiting on ${n.question.target} · ${span(now - n.question.created_at)}`;
  }
  if (n.finished) return n.done?.text ? `Done: ${n.done.text}` : "Done";
  if (n.gone) return "Pane gone";
  const what = n.display || n.derived || n.state;
  const label = what.charAt(0).toUpperCase() + what.slice(1);
  return n.last_activity ? `${label} · last active ${ago(now, n.last_activity)}` : label;
}

export function TreeList({
  nodes,
  highlight,
  now,
  detail,
}: {
  nodes: Node[];
  highlight?: string;
  now: number;
  detail: boolean;
}) {
  const base = Math.min(...nodes.map((n) => n.depth));
  return (
    <>
      {nodes.map((n) => {
        const hot = n.name === highlight || (detail && n.question?.target === "human");
        return (
          <div
            key={n.name}
            className={`node${hot ? " hot" : ""}${n.depth === base ? " root" : ""}`}
            style={{ marginLeft: (n.depth - base) * 16 }}
          >
            <div className="node-top">
              <span className="dot" style={{ background: dotColor(n) }} />
              <span className={`mono${n.finished ? " muted" : ""}`}>{n.name}</span>
            </div>
            {detail && <div className="node-say">{say(n, now)}</div>}
          </div>
        );
      })}
    </>
  );
}

export function Legend() {
  return (
    <div className="legend">
      <span><span className="dot" style={{ background: "var(--green)" }} />working</span>
      <span><span className="dot" style={{ background: "var(--amber)" }} />asking you</span>
      <span><span className="dot" style={{ background: "var(--red)" }} />stalled or gone</span>
      <span><span className="dot" style={{ background: "var(--grey)" }} />done</span>
    </div>
  );
}
