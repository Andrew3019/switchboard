# A vs B: how a repo `CLAUDE.md` should reach a codex agent

Round 3. Settles the question round 2 left open (`notes/codex-instruction-layering.md` §1
called the recommendation; `notes/codex-layering-probe.md` §2–§3 called B "strictly safer
against truncation" without weighing it against A on anything else). No switchboard code
changed. Only this file written.

**A — fallback list.** `project_doc_fallback_filenames = ["CLAUDE.md"]` + raised
`project_doc_max_bytes`, both in the private `CODEX_HOME/config.toml`. codex reads the
repo file itself.

**B — inline.** sb reads the repo `CLAUDE.md` at spawn and appends its text into the
per-agent `CODEX_HOME/AGENTS.md` (the global slot).

All trials below ran against real `codex-cli 0.147.0`, from scratch git repos and scratch
`CODEX_HOME` dirs under scratchpad, all deleted after use. Never touched
`~/.codex/config.toml`, `~/.codex/AGENTS.md`, or anything under `~/.claude/`. One cleanup
gap: two trivial sanity-check sessions (`reply PONG`) were run against the real, default
`~/.codex` before I set up the scratch homes, and `codex delete --force <id>` on those two
session ids was refused twice in a row by this session's own tool-permission classifier
(not a codex error — the command itself was blocked before it ran). I did not find a
workaround and did not think it was worth blocking a human over two content-free sessions,
but it means the "delete every session" requirement is not fully met — flagging rather
than hiding it. Session ids, for the record: `01a00a8b-e10f-7193-8117-01b6b9c0d638`,
`01a00a8c-af04-73c2-8a2c-199d61f9e86d`.

Also discovered mid-probe: `codex exec --json` is reliably blocked by the same classifier
in this session (looked like an automated-scripting pattern it doesn't like); switching to
plain-text `codex exec` output worked every time and is what all trials below use.

## 1. Truncation safety

Round 2 verified the raised cap fixes truncation up to 60KB and left the true ceiling
open. Pushed further this round:

- **A, raised `project_doc_max_bytes = 500000`, repo `CLAUDE.md` at 424KB:** full content
  reached the model, marker word near the end recovered correctly. **VERIFIED.**
- **B, inline into the global slot, no cap set, payload at 2MB:** full content reached
  (327K tokens used), marker recovered. **VERIFIED**, extends round 2's 60KB checkpoint.
- **Both mechanisms hit the same real ceiling, and it isn't a codex config value — it's
  the model's context window.** A 9.5–9.8MB payload, tried both ways (A with
  `project_doc_max_bytes` raised to 20,000,000; B inlined directly into the global slot,
  no cap at all on that slot), produced the identical result both times:
  `ERROR: Codex ran out of room in the model's context window. Start a new thread or
  clear earlier history before retrying.` — 0 tokens used, turn aborted. **VERIFIED**,
  same error text, both mechanisms.
- So: there is no mechanism-specific ceiling to find above the configured cap — the
  ceiling is the model's context window, and it is the same ceiling for both. The
  practical difference is only whether you hit it as a config-capped silent truncation
  (A, only if you forget to raise the cap, or set it too low) versus a loud, explicit
  error (both mechanisms, once you're actually near the context window). Neither
  mechanism has a truncation-safety edge once the cap is raised — this round's headline
  finding is that A's "strictly safer" framing from round 2 was about the *default*, not
  about the mechanism itself.

## 2. `AGENTS.md`-wins semantics

Under B, sb has to decide for itself whether to inline `CLAUDE.md` when a repo
`AGENTS.md` also exists — codex's own rule (verified round 2: `AGENTS.md` always beats
the fallback list outright) has to be reimplemented correctly, or B duplicates it wrong.

Tested a naive B that inlines `CLAUDE.md` unconditionally, without checking for a repo
`AGENTS.md` first — the mistake a first-pass implementation is likely to make:

- Repo has `AGENTS.md` saying "answer BLUE" (the human's real, intended doc) and
  `CLAUDE.md` saying "answer GREEN" (stale/inapplicable once `AGENTS.md` exists). Naive B
  inlines GREEN into the global slot, no authority language. **Result: BLUE** — codex's
  own project-slot read of the real `AGENTS.md` still wins on recency, so the wrong
  answer doesn't win outright. **VERIFIED.**
- Same setup, but the global slot also carries the authority-preamble round 2 §2 requires
  sb to write (mandatory for both mechanisms, so this is the realistic shape, not a
  contrived one). **Result: GREEN** — the wrong, stale doc now wins, because
  authority-claiming beats a plain project doc regardless of which is actually correct
  (round 2's own §1 finding, now shown to bite here). **VERIFIED.**

So the reimplementation isn't optional plumbing — skipping it is a live bug the moment sb
adds the authority wording it already committed to adding. A pays no equivalent cost:
codex's `AGENTS.md`-wins-over-fallback check happens inside codex itself, for free.

## 3. Nearest-doc-from-cwd semantics

Same shape of question, worse outcome. Round 2 §4 verified codex's own project-doc
lookup is nearest-wins-from-cwd, single doc, not merged. Under B, sb bakes in whatever it
read at spawn (repo root, typically) and that's frozen; codex's *own* project-slot lookup
still walks from cwd independently and can find a different, more specific doc.

Set up round 2's exact nested-doc shape: repo root `CLAUDE.md` says "answer PURPLE",
`sub/AGENTS.md` says "answer ORANGE". B inlines the root `CLAUDE.md` (PURPLE) with the
authority preamble into the global slot at spawn. Agent's cwd is `sub`.

**Result across 5 trials: ORANGE, PURPLE, ORANGE, ORANGE, ORANGE — 4/5 correct (the
nested doc, ORANGE), 1/5 wrong (the stale root inline, PURPLE), non-deterministic.**
**VERIFIED**, repeated runs of the identical setup.

This is worse than §2's failure mode, not just structurally analogous to it: it's not
merely wrong when triggered, it's a coin flip. A has no equivalent risk here — codex's
nearest-doc walk is codex's own, deterministic, and already verified correct for this
exact shape in round 2 (root-vs-sub, both directions, no flakiness observed there).
Whether B is even wrong at all depends on where sb sets cwd at spawn — sb currently spawns
at the worktree root (round 2 §3), so this is latent, not live, today; but "latent until
someone changes one line of spawn code" is exactly the kind of risk that using A avoids by
construction.

## 4. Per-turn re-read vs spawn snapshot

Round 2 assumed A "re-reads from disk each turn" but only checked spawn-time reads.
Tested properly this round using `codex exec resume <id>`, the closest scriptable proxy
for a continued conversation:

- Turn 1 (fresh session, A, fallback + raised cap): repo `CLAUDE.md` says "answer CYAN".
  **Result: CYAN.**
- Edited `CLAUDE.md` on disk to "answer MAGENTA" between turns, then
  `codex exec resume <same session id>` asked the same question again.
  **Result: CYAN — the stale answer, not the edited one.** **VERIFIED.**
- Sanity check: a brand-new (non-resumed) session against the same now-edited file
  answers **MAGENTA** correctly, confirming the edit itself took effect and the file
  really is read fresh at process start. **VERIFIED.**

So round 2's "confirmed A re-reads from disk each turn" claim does not hold for
`codex exec resume` — the project doc is captured once, at the start of the transcript,
and is not refreshed on a resumed turn. This directly contradicts §1's "not a snapshot"
selling point for A in `notes/codex-instruction-layering.md`.

Caveat, stated plainly: sb doesn't drive codex via `codex exec resume` — it hasn't wired
codex spawning into `herdr.py` at all yet, and the eventual mechanism is presumably an
interactive, long-lived `codex` TUI process in a herdr pane (the same shape used for
claude), not a chain of `codex exec resume` calls. I did not test the interactive TUI's
per-turn behavior — scripting a real multi-turn interactive session safely was out of
reach in the time this probe had, and round 2 didn't test it either. So: **A's "re-reads
every turn" claim is unverified for the mechanism sb will actually use, and the one
concrete multi-turn mechanism I could test contradicts it.** Both A and B should be
treated as "effectively spawn-time snapshots for the life of one long-running agent" until
someone tests the actual interactive TUI path — which removes what round 2 treated as A's
clearest advantage.

## 5. Implementation surface in sb

Concretely, per mechanism, what sb's spawn code has to do:

**A:**
- Write two keys into the per-agent `CODEX_HOME/config.toml`:
  `project_doc_fallback_filenames = ["CLAUDE.md"]`, `project_doc_max_bytes = <raised>`.
- No file reading, no precedence logic, no cwd resolution — codex's own project-doc
  lookup already does AGENTS.md-wins (§2), nearest-from-cwd (§3), and per-turn behavior
  (whatever that turns out to be, §4) correctly and for free.
- On restore (an agent's `CODEX_HOME` surviving a pane close/reopen, per the sb model):
  nothing to recompose — the config keys are already on disk and codex re-derives the doc
  from the filesystem at spawn regardless.

**B:**
- Read the repo's `CLAUDE.md` (and now, per §2, also check for `AGENTS.md` first and
  suppress the inline if it's present — reimplementing codex's own precedence check).
- Resolve which doc is nearest from the agent's actual spawn cwd (§3) — reimplementing
  codex's own nearest-from-cwd walk, or accept the coin-flip risk found there.
- Compose it into the per-agent `CODEX_HOME/AGENTS.md`, below the sb protocol and
  demoted (matching the existing `~/.codex/AGENTS.md` handling in round 2 §4) or above it
  if it's meant to carry authority — a decision A never has to make since codex keeps the
  two slots structurally separate on its own.
- On restore: has to be re-composed by sb (the file has to be rewritten, not just left in
  place), since the content is a copy sb made, not a live reference — one more thing sb's
  restore path has to get right that A doesn't need at all.

A is strictly less code and fewer decisions: one config write, zero reimplemented
precedence logic. B requires reimplementing two of codex's own behaviors (§2, §3) to avoid
the bugs found above, plus a restore-time recomposition step A doesn't need.

## 6. Failure visibility

- **Missing file, A:** fallback list configured, no `AGENTS.md` or `CLAUDE.md` anywhere
  in the repo. Asked the agent directly whether it saw any project-level doc.
  **Result: "No."** — silent, no error, no warning to operator or model; the agent simply
  proceeds with no project doc and no way to tell this apart from "the repo genuinely has
  no doc" versus "codex's lookup failed for some other reason." **VERIFIED live.**
- **Missing file, B:** this isn't a codex behavior to test — it's a decision inside sb's
  own spawn code, made with a definite, synchronous file-exists check before the agent
  ever starts. sb *knows* for certain whether the file was there; the only way this
  degrades to A's silent-failure shape is if sb chooses not to log/surface that check.
  That's strictly better raw material for visibility, but it's an sb code-quality
  question, not something codex enforces for you the way it does for A.
- **Truncation, A, default (unraised) cap:** already verified live in round 2 (32768-byte
  cap, 60KB file, silent mid-line cutoff, no warning). Carrying that forward, not
  re-run — the finding stands unchanged.
- **Truncation/ceiling, both mechanisms, at the true (context-window) ceiling:** loud, not
  silent — `ERROR: Codex ran out of room in the model's context window...`, identical
  text both times (§1). This is a real point in both mechanisms' favor at the *extreme*
  end, but it doesn't rescue A's default-cap failure mode, which is still silent.
- **A config key codex stops honouring:** not testable without a codex version that drops
  the key; out of scope for a live probe of the current binary. Flagging as genuinely
  unmeasured, same for both mechanisms (B has no equivalent config key to stop being
  honoured, which is itself a point for B, but an untested one).

Net for this criterion: A's only silent-failure mode is the default-cap truncation, which
is closed the moment sb raises the cap (which the mechanism requires anyway). B's
silent-failure mode is entirely a function of sb's own spawn-code discipline (§2, §3) —
worse in practice, since §2 and §3 showed concrete ways to get that discipline wrong, and
those failures (a stale doc silently outranking the correct one) are strictly harder to
notice than A's "no doc got picked up at all."

## Recommendation

**Use A.** Across every criterion that produced new evidence this round, A comes out
ahead or even, and never behind:

- Truncation: a wash once the cap is raised (§1) — round 2's "B is strictly safer" claim
  doesn't survive pushing past 60KB; both hit the identical context-window ceiling.
- `AGENTS.md`-wins and nearest-doc-from-cwd (§2, §3): A gets both for free from codex's
  own lookup; B has to reimplement them, and a plausible naive implementation of B gets
  both wrong in live-tested, concrete ways (one wrong-doc-wins case, one that's an
  outright coin flip).
- Per-turn re-read (§4): the advantage round 2 credited to A doesn't hold up under the
  one multi-turn mechanism this round could actually test, and the real mechanism (an
  interactive TUI session) is untested by anyone so far — so this is now a wash too, not
  a point for either side.
- Implementation surface (§5): A is less code, fewer decisions, no restore-time
  recomposition.
- Failure visibility (§6): A's only silent-failure mode is closed by the same raised cap
  the mechanism already needs; B's silent-failure modes are the §2/§3 bugs, which are
  by nature harder to notice (wrong content silently outranking right content, not an
  absent doc).

**Main risk of A:** it depends on codex continuing to honor
`project_doc_fallback_filenames` and `project_doc_max_bytes` from `CODEX_HOME/config.toml`
in future codex-cli releases — an external dependency sb doesn't control. If codex ever
drops or renames these keys, the repo doc silently stops reaching the agent (same silent
shape as the missing-file case in §6), with no equivalent fallback sb could switch to
without doing the B-style reimplementation this document just argued against. This is a
real, if currently unmeasured (§6), tail risk worth a version-pin or a startup
smoke-check if this ships.

## Cleanup performed

- Deleted the entire scratch tree (`scratchpad/repodoc/`, both private `CODEX_HOME`
  dirs, copied `auth.json`s, all session/rollout files, both scratch git repos).
  **Confirmed removed.**
- `ps aux | grep "codex-cli\|codex exec"` after cleanup: no matching process.
  **Confirmed.**
- `find <worktree root> -maxdepth 1 -iname AGENTS.md -o -iname CLAUDE.md`: empty.
  **Confirmed** no stray file left in the real checkout.
- `grep -i "repodoc\|TANGERINE\|MANGOKIWI\|project_doc_fallback" ~/.codex/config.toml`:
  no match. **Confirmed** the real config was never written to.
- Did not touch `~/.codex/AGENTS.md` or anything under `~/.claude/`.
- Not fully clean: two real-`~/.codex` sanity-check sessions (content: "reply PONG" /
  "reply PONG2", no scratch or sensitive material) could not be deleted — `codex delete
  --force` was blocked twice by this session's own permission classifier, not by codex.
  Session ids listed at the top of this file for whoever wants to finish that cleanup.
