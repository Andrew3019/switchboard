# Do you still need Cursor open? — findings & options

Discussion pass (not a build). Question: can Andrew stop keeping Cursor open just to read
markdown + "decisions-type stuff", via a shortcut / existing tool / small localhost thing?
firstmate was the named inspiration.

## The ask has two halves
1. **Read markdown files** without an editor — `DESIGN-TRUTH.md`, `README.md`, and ~200 loose
   `.md` across `notes/` (129!), `learnings/` (36), `research/` (21), `design/` (13),
   `reference/`, plus live `.switchboard/{briefs,tasks,handoffs}`.
2. **See "decisions-type stuff"** — what's decided, what's still open, what changed.

They want different solutions. Half 2 is the part Cursor never did well anyway.

## What firstmate actually is (important)
- `kunchenguid/firstmate` is an **agent-orchestration distro** — a close cousin of switchboard
  (single liaison + crew of agents in worktrees), **not a viewer**.
- It has **no web app / TUI / localhost UI at all** — just shell scripts that print markdown
  digests into the chat transcript.
- So it does **not** solve "stop opening Cursor". Its value is *content-shape* ideas:
  - **Bounded "bearings" digest** — one compact state-of-everything view, not a firehose.
  - **Persistent "OPEN DECISIONS" section** surfaced on *every* view, so a decision never gets
    buried in the log.
  - **Decision records as first-class objects** — owner + explicit resolve step, not just prose.

## What switchboard/herdr already give you (so we don't rebuild it)
- `sb status`, `sb board` (live curses agent picture; plans plugin draws plan DAGs on it),
  `sb inspect`, `sb plugin plans show`, `sb presets` — all **terminal**, all switchboard's *own*
  state (agents, plans, presets).
- **Zero** of it renders markdown, browses a file tree, searches docs, or shows diffs.
- **No web server / browser UI exists in the repo at all** (grepped: no flask/fastapi/http.server/
  html/react). herdr's one hook that could host a pane (`plugin pane.open`) is flagged
  experimental, not for v0.
- **The gap = every plain `.md` file.** That's exactly what still forces Cursor open.

## Options

**A — Off-the-shelf, zero build (fastest).**
Point an existing previewer at the repo: `grip` (GitHub-style localhost preview), `glow` (terminal
md renderer), or an **Obsidian vault** over the repo root (tree + search + backlinks + graph, free).
- ✅ Working today, no code to maintain. ✅ Obsidian gives tree+search+diff-ish history for free.
- ❌ Generic — knows nothing about switchboard state (plans, open decisions). Still a separate app.

**B — Thin `sb view` localhost server (small build).**
~single-file stdlib-Python server: file tree over the doc dirs + `.switchboard/{briefs,tasks,
handoffs}`, render `.md`→HTML, search, live-reload; later fold in `sb plugin plans show` output.
- ✅ Switchboard-native, one command, no deps, kills the "open Cursor to read" need entirely.
- ✅ A natural home to later add the decisions digest (Option C).
- ❌ Introduces the repo's **first web surface** — a new thing to keep working in a
  terminal-native tool. Real architecture decision, not just code.

**C — `sb bearings` decisions digest (no viewer, addresses half 2).**
Steal firstmate directly: a bounded terminal digest folding DESIGN-TRUTH decisions + open
questions + recent handoffs, with a persistent **OPEN DECISIONS** section.
- ✅ Terminal-native, matches existing `sb` surfaces, cheap. ✅ Solves the "decisions" half well.
- ❌ Doesn't render/browse arbitrary markdown — not a Cursor replacement on its own.

**D — Terminal renderer wired into sb (`sb show <file>`).**
Pipe any repo `.md` through `glow`/`bat` + an fzf tree picker. Stays 100% terminal, matches the
board/status ethos, no browser.
- ✅ Consistent with everything switchboard already does, no web stack.
- ❌ No diff; terminal is weaker than a browser for long docs / wide tables.

## Recommendation
- **Quick win, today:** try **Option A / Obsidian** over the repo — it likely covers the "read
  markdown" half with zero build, and tells us whether a browser tree+search is even what you want.
- **If you want it switchboard-native:** **B (`sb view` localhost) + C (decisions digest)** is the
  real answer — B replaces Cursor-as-reader, C is the firstmate-shaped "decisions" surface Cursor
  never gave you. Start with C (cheap, terminal, no new surface); add B only if Obsidian proves
  a browser view is worth the repo's first web server.
- **One reason it's your call:** B means the first web/browser surface in an intentionally
  terminal-native tool — that's an architecture direction, not just a task.
- **Cost if wrong:** A/C are throwaway-cheap. B is a few hundred lines of a new surface to maintain.

## Sources
- firstmate findings: `.switchboard/briefs/scout-firstmate/findings.md`
- local inventory + gap: `.switchboard/briefs/scout-local-context/findings.md`
