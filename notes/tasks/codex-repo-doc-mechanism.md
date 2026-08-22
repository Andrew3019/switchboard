# Probe task — settle how repo CLAUDE.md should reach a codex agent

INVESTIGATION + EXPERIMENT. No switchboard code changes. Write only your own notes file.

Read first: `notes/codex-instruction-layering.md` §1 and `notes/codex-layering-probe.md`
§2–§4. Do not redo what they verified.

## The question to settle

Two candidate mechanisms for making a repo's `CLAUDE.md` apply to an sb-spawned codex
agent:

- **A. Fallback list** — `project_doc_fallback_filenames = ["CLAUDE.md"]` plus a raised
  `project_doc_max_bytes`, both in the private `CODEX_HOME/config.toml`. codex reads the
  repo file itself, as its project doc.
- **B. Inline** — sb reads the repo `CLAUDE.md` at spawn and appends its text into the
  per-agent `CODEX_HOME/AGENTS.md` (the global slot, which has no known size cap).

Round 2 chose A; the round-2 probe called B "strictly safer against truncation". Andrew
has not ratified either — he wants whichever is genuinely better across all aspects, with
evidence, and one recommendation rather than a restated tradeoff.

## Weigh these, and measure what is still unmeasured

1. **Truncation safety.** Does a raised `project_doc_max_bytes` reliably hold — across
   sizes well past the default, across TUI and `exec`, and set from `CODEX_HOME/config.toml`
   rather than `-c`? Is there an upper bound where it stops working or degrades? What is
   the real ceiling on the *global* slot above the 60KB already tested — push it until
   something breaks (or establish nothing does within any plausible size).
2. **`AGENTS.md`-wins semantics.** Under B, sb has to decide for itself whether to inline
   `CLAUDE.md` when a repo `AGENTS.md` also exists, and get that decision right. Under A
   codex decides. What does B have to reimplement, and where would it be wrong?
3. **Nearest-doc-from-cwd semantics.** Same question: under B, which file does sb even
   read, and what happens with nested docs or a non-root cwd?
4. **Per-turn re-read vs spawn snapshot.** Confirm A re-reads from disk each turn (edit
   the repo file mid-session and see whether the next turn reflects it). Establish what B
   would freeze, and whether that matters for a long-lived agent.
5. **Implementation surface in sb.** Which is less code and fewer decisions in the spawn
   path? Be concrete: name what each requires (config keys written vs file reading,
   precedence logic, cwd resolution, re-composition on restore).
6. **Failure visibility.** This is the one most likely to decide it: when each mechanism
   goes wrong, how does the operator find out? Silent mid-line truncation, a missing file,
   a stale snapshot, a config key codex stops honouring — for each, is there any signal, or
   does the agent just quietly run with the wrong rules? Test at least the truncation and
   missing-file cases live.

Test both mechanisms end to end, not just their parts. Include a realistic case: a repo
with a substantial real `CLAUDE.md` (use this repo's own docs as filler material if you
need bulk — copy into scratch, do not run agents against the real checkout).

## Deliverable

`notes/codex-repo-doc-mechanism.md`. You own that file and only that file. Structure it as
the six criteria above, each with evidence, then **one recommendation** stated plainly with
its main risk named. If the answer is genuinely "A for these cases, B for those", say so —
but only if the evidence forces it, and then give the rule for choosing.

Scratch dirs and private `CODEX_HOME`s only; never modify the real `~/.codex/config.toml`
or anything under `~/.claude/`; delete every session (`codex delete --force <id>`); no
unscoped `pkill`. Commit on the current branch, then `sb done` with a two-line summary
leading with the recommendation.
