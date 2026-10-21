import { useState } from "react";
import { enc, getJSON, post } from "./api";

export function AgentActions({ repo, name }: { repo: string; name: string }) {
  const [msg, setMsg] = useState<string | null>(null);
  const [log, setLog] = useState<string | null>(null);
  return (
    <>
      <span className="push" />
      <button
        className="btn"
        title="Moves focus inside herdr. It cannot bring the terminal window to the front."
        onClick={async () => {
          const r = await post(`/api/agent/${enc(repo)}/${enc(name)}/focus`);
          setMsg(r.ok ? "Focused in herdr." : r.error || "focus failed");
        }}
      >
        Focus in herdr
      </button>
      <button
        className="btn"
        onClick={async () => {
          if (log !== null) return setLog(null);
          try {
            const t = await getJSON<{ text: string }>(`/api/agent/${enc(repo)}/${enc(name)}/transcript`);
            setLog(t.text || "(empty)");
          } catch (e) {
            setLog(`No transcript: ${(e as Error).message}`);
          }
        }}
      >
        {log !== null ? "Hide transcript" : "Transcript"}
      </button>
      {msg && <div className="small muted full">{msg}</div>}
      {log !== null && <pre className="transcript full">{log}</pre>}
    </>
  );
}

export function MessageBox({ repo, name, onDone }: { repo: string; name: string; onDone: () => void }) {
  const [text, setText] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  return (
    <div className="field">
      <label className="lbl" htmlFor={`tell-${repo}-${name}`}>Message to {name}</label>
      <textarea id={`tell-${repo}-${name}`} rows={3} value={text} onChange={(e) => setText(e.target.value)} />
      <div className="row">
        <button
          className="btn primary"
          disabled={!text.trim()}
          onClick={async () => {
            const r = await post(`/api/agent/${enc(repo)}/${enc(name)}/tell`, { text });
            setMsg(r.ok ? { ok: true, text: "Sent." } : { ok: false, text: r.error || "failed" });
            if (r.ok) setText("");
          }}
        >
          Send
        </button>
        <button className="btn" onClick={onDone}>Cancel</button>
      </div>
      {msg && <div className={msg.ok ? "ok-msg" : "err-msg"}>{msg.text}</div>}
    </div>
  );
}
