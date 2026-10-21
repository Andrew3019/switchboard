export type Option = { label: string; detail: string | null; recommended: boolean };
export type Link = { title: string | null; target: string; kind: "url" | "file" };
export type Parts = {
  about?: string | null;
  catch_up?: string | null;
  blocked?: string | null;
  options?: Option[];
  links?: Link[];
};

export type Node = {
  name: string;
  parent: string | null;
  depth: number;
  role: string;
  state: string;
  derived: string | null;
  display: string | null;
  gone: boolean;
  finished: boolean;
  last_activity: number | null;
  created_at: number;
  branch: string | null;
  about: string | null;
  question: { id: number; target: string; body: string; created_at: number } | null;
  done: { text: string | null; at: number } | null;
};

export type PR = {
  number: number;
  title: string;
  url: string;
  branch: string;
  draft: boolean;
  review: string;
  checks: string | null;
  created_at: string;
  waiting_merge: boolean;
};

export type Question = {
  id: number;
  asker: string;
  target: string;
  body: string;
  created_at: number;
  escalated_at: number | null;
  escalated_from: string | null;
  last_reply_at: number | null;
  parts: Parts | null;
  top: string;
  top_about: string | null;
  tree: Node[];
};

export type Tree = {
  top: string;
  about: string | null;
  created_at: number;
  nodes: Node[];
  needs_you: number;
  latest_report: { agent: string; text: string; at: number } | null;
  prs: PR[];
};

export type Stuck = {
  name: string;
  gone: boolean;
  idle: number | null;
  unread: number;
  last_activity: number | null;
};

export type RepoState = {
  id: string;
  name: string;
  checkout: string;
  error?: string;
  status_error?: string | null;
  pr_error?: string | null;
  trees: Tree[];
  questions: Question[];
  between: Question[];
  stuck: Stuck[];
  prs: PR[];
};

export type State = { now: number; repos: RepoState[] };

export type Result = { ok: boolean; error?: string | null; result?: unknown };

export async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url, { credentials: "same-origin" });
  const body = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
  return body as T;
}

export async function post(url: string, body: object = {}): Promise<Result> {
  try {
    const r = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const out = await r.json().catch(() => ({ ok: false, error: `HTTP ${r.status}` }));
    if (!r.ok) return { ok: false, error: out.error || `HTTP ${r.status}` };
    return out as Result;
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

export const enc = encodeURIComponent;

export function ago(now: number, then: number | null | undefined): string {
  if (!then) return "never";
  return `${span(now - then)} ago`;
}

export function span(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 48) return m % 60 ? `${h} h ${m % 60} min` : `${h} h`;
  return `${Math.floor(h / 24)} days`;
}

export function safeUrl(target: string): string | null {
  try {
    const u = new URL(target);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}
