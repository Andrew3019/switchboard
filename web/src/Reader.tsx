import { useEffect, useMemo, useState } from "react";
import DOMPurify from "dompurify";
import { marked } from "marked";
import { enc, getJSON, safeUrl, ago } from "./api";
import { readerHref } from "./NeedsYou";

type File = { path: string; text: string; mtime: number };

DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName !== "A") return;
  const href = node.getAttribute("href") || "";
  if (href.startsWith("#")) return;
  const ok = safeUrl(href);
  if (ok) {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  } else if (!href.endsWith(".md")) {
    node.removeAttribute("href");
  }
});

function dirname(p: string): string {
  return p.slice(0, p.lastIndexOf("/"));
}

function resolvePath(base: string, rel: string): string {
  const parts = (rel.startsWith("/") ? rel : `${dirname(base)}/${rel}`).split("/");
  const out: string[] = [];
  for (const s of parts) {
    if (s === "..") out.pop();
    else if (s && s !== ".") out.push(s);
  }
  return "/" + out.join("/");
}

export function Reader({ repo, path, back, now }: { repo: string; path: string; back: string; now: number }) {
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [raw, setRaw] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setFile(null);
    setError(null);
    getJSON<File>(`/api/file?repo=${enc(repo)}&path=${enc(path)}`).then(setFile, (e) => setError(e.message));
  }, [repo, path]);

  const html = useMemo(() => {
    if (!file) return "";
    const clean = DOMPurify.sanitize(marked.parse(file.text, { async: false }) as string, {
      FORBID_TAGS: ["style", "form", "input", "button", "textarea", "select"],
      FORBID_ATTR: ["style", "class", "id"],
    });
    const doc = new DOMParser().parseFromString(clean, "text/html");
    doc.querySelectorAll("a[href$='.md']").forEach((a) => {
      const href = a.getAttribute("href") || "";
      if (!safeUrl(href)) a.setAttribute("href", readerHref(repo, resolvePath(path, href), back));
    });
    return doc.body.innerHTML;
  }, [file, repo, path, back]);

  return (
    <main className="reader">
      <div className="row baseline">
        <a href={`#/needs?at=${enc(back)}`} className="btn">Back to the question</a>
        <span className="mono small muted wrap">{repo} · {path}</span>
        {file && <span className="small muted">changed {ago(now, file.mtime)}</span>}
        <span className="push" />
        <button
          className="btn"
          onClick={() => {
            navigator.clipboard?.writeText(path).then(() => setCopied(true));
          }}
        >
          {copied ? "Copied" : "Copy path"}
        </button>
        <button className="btn" onClick={() => setRaw(!raw)}>{raw ? "Show rendered" : "Show raw"}</button>
      </div>
      {error && <div className="card md err-msg">Cannot open this file: {error}</div>}
      {file && (raw ? (
        <pre className="card md raw">{file.text}</pre>
      ) : (
        <article className="card md" dangerouslySetInnerHTML={{ __html: html }} />
      ))}
    </main>
  );
}
