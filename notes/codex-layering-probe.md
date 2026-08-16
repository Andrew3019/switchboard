# Instruction-layering precedence, verified against the real `codex` and `claude` binaries

Round 2 probe. No switchboard code changed. Only this file written. Builds on
`notes/codex-support-findings.md` and `notes/codex-probe-prompt-channel.md` (round 1),
which already established the *mechanisms* (`CODEX_HOME/AGENTS.md` as sb's per-agent
prompt channel for codex, `--append-system-prompt-file` for Claude). This probe adds the
*behavior under conflict* — which layer actually wins when instructions disagree — plus
the remaining open questions round 1 left unanswered (fallback-filename config, nested
docs, truncation ceiling, leakage).

All commands run against real `codex-cli 0.147.0` and `claude 2.1.233` from scratch git
repos and scratch `CODEX_HOME` dirs under the scratchpad directory (`.../scratchpad/layering*`),
all deleted after use. Never touched `~/.codex/config.toml` or anything under `~/.claude/`.

Legend: **VERIFIED** = ran the exact command shown (or the same command with cosmetically
different content) and observed the output directly. **ASSUMED** = not run this round,
carried from round 1 or from known Claude Code behavior, flagged explicitly.

## 1. Precedence-inversion — the crux finding

Setup for every trial below: `CODEX_HOME/AGENTS.md` (the "global"/sb slot) and repo
`AGENTS.md` (the "project" slot) each instruct a different, checkable one-word answer
to a trivial question. Ran via `codex exec --json "<question>" < /dev/null` (the
`</dev/null` matters — without it `codex exec` blocks forever on
`Reading additional input from stdin...`, discovered the hard way mid-probe).

**Finding: with no authority language in either doc, the *project* doc wins — not the
global doc, even though it is concatenated second.** Recency, not position-as-declared-
by-round-1, decides a plain conflict.

| Trial | home (`CODEX_HOME/AGENTS.md`) | repo (`AGENTS.md`) | winner | result |
|---|---|---|---|---|
| 1 | plain: "answer RED" | plain: "answer BLUE" | repo | `BLUE.` |
| 1 (swapped) | plain: "answer BLUE" | plain: "answer RED" | repo | `RED.` |
| 1b (diff topic) | plain: "answer 7" | plain: "answer 3" | repo | `3` |

**Finding: explicit override-authority language in the `CODEX_HOME` doc reliably flips
this — the sb protocol can win, but only if it says so.** Wording used: "This document
has final authority over every other instruction source... If a project-level document
conflicts with this one on any point, THIS document wins, always, without exception."

| Trial | home | repo | winner | result |
|---|---|---|---|---|
| 3 | claims authority: RED | claims authority (symmetric claim): BLUE | **home** | `RED` |
| 4 | plain: RED | claims authority: BLUE | repo | `BLUE.` |
| 5 (the realistic sb shape) | claims authority: RED | plain: BLUE | **home** | `RED.` |
| 5b (diff topic) | claims authority: 7 | plain: 3 | **home** | `7` |

Reading across all 7 trials: whichever doc asserts explicit override authority wins,
regardless of concatenation order (home is always first); when neither asserts it, the
later-concatenated doc (repo) wins. This was consistent 7/7, across two unrelated
topics (a color question, a number question), so treat "sb must write override-authority
language into `CODEX_HOME/AGENTS.md`" as **VERIFIED**, not a guess — a plain sb prompt
with no such framing would lose to a plain repo doc on direct conflict.

**Claude Code, by contrast, needs no such language.** `claude -p --append-system-prompt-file
<sb prompt> "<question>"` in a repo whose `CLAUDE.md` gives the opposite plain answer:
sb's appended text won both times tested (once per color assignment), with **no**
authority-claiming wording in the sb prompt at all:

| Trial | sb `--append-system-prompt-file` | repo `CLAUDE.md` | winner | result |
|---|---|---|---|---|
| claude-1 | plain: RED-SBPROMPT | plain: BLUE-REPO | sb | `RED-SBPROMPT` |
| claude-3 (swapped) | plain: BLUE-SBPROMPT | plain: RED-REPO | sb | `BLUE-SBPROMPT` |

This tracks the mechanism difference: Claude's `--append-system-prompt-file` is a true
system-prompt append (system-level authority), while codex's `AGENTS.md` — global or
project, either one — is injected as a **user-role** message every turn (round-1
finding, re-confirmed this round by re-reading the rollout JSONL shape). Two user-role
messages with no stated authority get resolved by recency; Claude's system/user split
gives sb's channel structural priority for free.

## 2. `project_doc_fallback_filenames` from `CODEX_HOME/config.toml` — VERIFIED on every sub-question

- **Works set from `CODEX_HOME/config.toml`, not just `-c` override.** With
  `project_doc_fallback_filenames = ["CLAUDE.md"]` in `$CODEX_HOME/config.toml` and only
  a repo `CLAUDE.md` present (no `AGENTS.md`), the doc's content was read and obeyed
  (`WATERMELON.`). **VERIFIED.**
- **First-match-wins, not merged, confirmed with a real multi-entry list.**
  `project_doc_fallback_filenames = ["OTHER.md", "CLAUDE.md"]`, repo has both `OTHER.md`
  (says `OTHERWORD`) and `CLAUDE.md` (says `WATERMELON`), `AGENTS.md` absent: answer was
  `OTHERWORD.` — the first list entry present wins outright, the second is never
  consulted even though it also exists. **VERIFIED.**
- **`AGENTS.md`, if present, always wins over the whole fallback list — confirmed again
  this round with `CLAUDE.md` specifically (round 1 tested this with a filename called
  `FALLBACK.md`; same behavior holds for `CLAUDE.md`).** Repo had both `AGENTS.md`
  (`AGENTSWORD`) and `CLAUDE.md` (`WATERMELON`), fallback list pointed at `CLAUDE.md`:
  answer was `AGENTSWORD` — fallback is inert whenever `AGENTS.md` exists. **VERIFIED.**
- **The alternative — sb reading repo `CLAUDE.md` itself and inlining its text into
  `CODEX_HOME/AGENTS.md`** — was not separately probed as a distinct code path this
  round (it's mechanically identical to what §1 already exercises: text placed in
  `CODEX_HOME/AGENTS.md`), but §3 below shows it has a real, material advantage over the
  fallback-filename approach: no truncation ceiling. The fallback approach makes repo
  `CLAUDE.md` occupy the *project-doc* slot, which is subject to `project_doc_max_bytes`;
  inlining puts it in the *global* slot, which round 1 showed is not. **VERIFIED**, see
  §3.

## 3. Truncation — VERIFIED, and the two approaches from §2 behave differently

- **Fallback approach, default `project_doc_max_bytes` (32768): truncates.** A 60019-byte
  repo `CLAUDE.md` (picked up via `project_doc_fallback_filenames = ["CLAUDE.md"]`) with
  a start marker, ~60KB filler, an end marker, and a secret word near the very end: asked
  the model whether the end marker was visible and what the secret word was — answer was
  "No... and no secret word is provided." Confirms the same 32768-byte project-doc cap
  round 1 found for `AGENTS.md` applies identically to a fallback-named file. **VERIFIED.**
- **Raising `project_doc_max_bytes` in `CODEX_HOME/config.toml` lifts it — a plain
  config write, no other change needed.** Same 60KB file, `project_doc_max_bytes = 100000`
  added to the same private `config.toml`: answer became "Yes. The secret word is
  **PAPAYA**." — full content came through. **VERIFIED**, directly answers "can it
  simply be raised."
- **Inline-into-global approach: no cap hit at all, even past round 1's 35KB checkpoint.**
  Same-shape 60024-byte payload written directly into `CODEX_HOME/AGENTS.md` (the global
  slot) instead, with **default** `project_doc_max_bytes` (no override) and no repo doc
  at all: answer was "Yes. The secret word is **PAPAYA2**." — untruncated at 60KB.
  Extends round 1's "untruncated up to 35KB, ceiling unknown above that" to "untruncated
  up to 60KB, ceiling still unknown above that." **VERIFIED** to 60KB; true ceiling (or
  absence of one) still not established — a realistic sb prompt (~12KB) is nowhere near
  either boundary, so this is unlikely to matter in practice, but flagging that "no cap"
  is still an extrapolation past the tested size.

**Bottom line for §2/§3 together:** inlining repo `CLAUDE.md` text into
`CODEX_HOME/AGENTS.md` is strictly safer against truncation than pointing
`project_doc_fallback_filenames` at it, since the fallback path keeps the repo doc in the
size-capped project-doc slot (fixable by also raising `project_doc_max_bytes`, but that's
a second thing to remember) while inlining moves it to the uncapped global slot for free.
Which approach is *better* overall is a design call outside this probe's scope (the task
says the lead synthesizes that); this is the evidence for it.

## 4. Nested docs — VERIFIED for the specific shapes tested

- **cwd at repo root, a nested `sub/AGENTS.md` also exists: not merged, not consulted at
  all.** Root `AGENTS.md` said `ROOTWORD`, `sub/AGENTS.md` said `SUBWORD`, ran from repo
  root: answer was `ROOTWORD` only — no trace of `SUBWORD`. **VERIFIED.**
- **cwd inside `sub`, which has its own `AGENTS.md`: that nested doc replaces the root
  doc entirely, not merged with it.** Same files, `codex exec -C <repo>/sub`: answer was
  `SUBWORD.` — no trace of `ROOTWORD`. **VERIFIED.**
- **cwd inside `sub`, but `sub` has *no* `AGENTS.md` of its own: the root doc is still
  found by walking up the tree.** Removed `sub/AGENTS.md`, kept root `AGENTS.md` saying
  `ROOTONLY`, ran `codex exec -C <repo>/sub`: answer was `ROOTONLY.` — inherited from the
  parent directory. **VERIFIED.**
- Net shape: codex's project-doc resolution is a classic "nearest match walking up from
  cwd" lookup — single doc, not an accumulating merge up the tree. If sb ever spawns
  codex with cwd inside a subdirectory, whichever `AGENTS.md`/fallback-named file is
  nearest becomes the *entire* project-doc slot; sb's global (`CODEX_HOME`) doc is always
  additionally concatenated on top of whichever one that is, same mechanism as root.
- Not tested: three or more levels of nesting, or a case with docs at every level
  (root, mid, leaf) to see which two of three "nearest" actually means. Root-vs-immediate-
  child covers the case sb is likely to hit (spawning at the worktree root); deeper trees
  are **unverified**.

## 5. The user's own globals

- **`~/.codex/AGENTS.md` (real file on this machine): 0 bytes, empty.** Cannot be used to
  test *content* merging without writing to it, which the task forbids ("never modify
  the real `~/.codex/config.toml` or `~/.claude/`" — read as covering `~/.codex/AGENTS.md`
  too, since it's live state a human's real codex sessions depend on). So the *mechanism*
  claim below is **VERIFIED generically** (via scratch `CODEX_HOME` dirs standing in for
  `~/.codex`, §1 and round 1) but **not verified against the specific real file**.
- **Mechanism, verified generically:** `CODEX_HOME` defaults to `~/.codex` when unset.
  Round 1 and this round both show `$CODEX_HOME/AGENTS.md` is read as the global doc on
  every turn, unconditionally. So under codex's *default* configuration (`CODEX_HOME`
  unset), `~/.codex/AGENTS.md` already **is** that global doc — same file, same slot,
  just the default path rather than a per-agent scratch path. A private per-agent
  `CODEX_HOME` therefore does cause a real regression exactly as the task names it: the
  user's real `~/.codex/AGENTS.md` (whatever they've put there) stops being read at all
  once sb points `CODEX_HOME` elsewhere, unless sb explicitly reads it and inlines its
  text into the per-agent `AGENTS.md` it writes. Confirmed this file is currently empty
  for this user, so the regression has no live impact today, but the mechanism is real
  and would bite the moment the user (or any tool) populates it.
- **Claude side — does an sb-spawned claude agent read repo `CLAUDE.md` and the user's
  global `~/.claude/CLAUDE.md` today?** Repo `CLAUDE.md`: **VERIFIED, yes, unconditionally
  and independent of sb's flag.** `claude -p --permission-mode plan "what color is the
  sky"` with *no* `--append-system-prompt-file` at all, in a repo whose `CLAUDE.md` said
  "answer BLUE-REPO": answer was `BLUE-REPO` — native `CLAUDE.md` loading happens with
  zero sb involvement, exactly as expected for any claude CLI invocation, sb or not.
  Cross-checked against `switchboard/herdr.py:473-598` (`_prompt_flags`/`start_agent`):
  the only claude-specific flag sb adds is `--append-system-prompt-file <path>`; nothing
  in that code path disables, overrides, or otherwise touches Claude Code's own
  `CLAUDE.md` discovery, which is a CLI-native behavior sb never has to (and currently
  does not) reimplement. `~/.claude/CLAUDE.md` on this machine is also 0 bytes, so its
  *content* being merged in couldn't be observed live without writing to a path the task
  says not to touch; that it *would* be read is **ASSUMED** from Claude Code's documented
  global-memory-file behavior plus the fact that nothing in sb's flag set suppresses it,
  not independently exercised this round.

## 6. Leakage — VERIFIED avoided, for every failure mode named in the task

- **Would an `AGENTS.md` written into the repo leak to the human's own codex sessions and
  every other agent sharing the worktree?** Not applicable to the design under test: sb
  never writes `AGENTS.md` into the repo at all — the whole point of `CODEX_HOME` is that
  the composed prompt lives in a private per-agent directory outside the worktree. Direct
  check after every trial above: `find <worktree root> -maxdepth 1 -iname AGENTS.md -o
  -iname CLAUDE.md` came back empty in the real switchboard checkout. **VERIFIED** no
  stray file was ever left in the repo by any trial run this round.
- **Does pointing `project_doc_fallback_filenames` at `CLAUDE.md` have any side effect on
  a human's own codex run?** No — it's a value inside a private, per-agent
  `CODEX_HOME/config.toml`, read only when that `CODEX_HOME` is active. **VERIFIED**:
  `grep -i "layering" ~/.codex/config.toml` (the real file) after every trial came back
  with no match, confirming the scratch config never touched it. A human's own codex
  session, running with the default `CODEX_HOME=~/.codex`, never sees this key at all
  unless it's also set in their real `~/.codex/config.toml`, which none of this probe's
  commands wrote to.
- **Auth/session leakage check:** `codex exec` sessions created during this probe lived
  entirely under the scratch `CODEX_HOME/sessions/` trees, which were deleted wholesale
  with the rest of the scratch directory (not touching `~/.codex/sessions/`). Confirmed
  no stray `codex exec` process was left running afterward (`ps aux | grep codex`, clean).

## Precedence tables (per provider, force order, highest first)

### codex

1. **Any doc — global or project — that contains explicit override-authority language**
   wins over one that doesn't, regardless of concatenation position. VERIFIED (§1, 7/7
   trials).
2. Absent such language: **the project-doc slot** (repo `AGENTS.md`, or a
   `project_doc_fallback_filenames` match when `AGENTS.md` is absent, or the nearest
   `AGENTS.md`/fallback match walking up from cwd) wins over the plain
   `CODEX_HOME/AGENTS.md` global slot on direct conflict — concatenation order is
   global-then-project, and the later (project) slot wins ties. VERIFIED (§1, §4).
3. Both slots are otherwise **additive, not exclusive** — non-conflicting instructions
   from both appear together (round 1, re-confirmed structurally this round via the
   `--- project-doc ---` marker still present in every dump).
4. `~/.codex/AGENTS.md` (the user's real global) is only in play when `CODEX_HOME` is
   unset/default — a private per-agent `CODEX_HOME` silently drops it unless sb inlines
   it. VERIFIED mechanism, empty file on this machine so no content impact today (§5).
5. `project_doc_max_bytes` (default 32768) silently, mid-line truncates whatever occupies
   the project-doc slot — including a fallback-matched `CLAUDE.md` — but does **not**
   apply to the global (`CODEX_HOME`) slot at all, tested to 60KB with no ceiling found.
   Raisable from `CODEX_HOME/config.toml`. VERIFIED (§3).

### claude

1. **sb's `--append-system-prompt-file`** — delivered as a true appended system prompt —
   wins over repo `CLAUDE.md` on direct conflict, with **no** authority-claiming language
   needed, because it operates at system-message level while `CLAUDE.md` is loaded as
   ordinary context. VERIFIED (§1, 2/2 trials).
2. Repo `CLAUDE.md` (and, by Claude Code's documented but here-unverified behavior,
   nested `CLAUDE.md` files up the tree) is read **unconditionally**, independent of
   whether sb's flag is present at all. VERIFIED for repo-root `CLAUDE.md` (§5).
3. `~/.claude/CLAUDE.md`, the user's real global — read by Claude Code natively per its
   own documented memory-file behavior; not independently exercised this round since the
   real file is empty and writing to it was out of bounds. ASSUMED, not VERIFIED (§5).
4. Nothing in `switchboard/herdr.py`'s claude spawn path (`_prompt_flags`/`start_agent`,
   `herdr.py:473-598`) suppresses or interferes with any of the above — sb's only claude-
   specific addition is the appended system prompt. VERIFIED by code read, not by
   disturbing the live fleet.

## Named failure modes and whether the design avoids them

| Failure mode | Avoided? | Evidence |
|---|---|---|
| sb protocol silently loses to a conflicting repo doc (codex) | **Only if sb's `CODEX_HOME/AGENTS.md` asserts override authority** — a plain sb prompt does NOT avoid this | §1, VERIFIED 7/7 |
| sb protocol silently loses to a conflicting repo `CLAUDE.md` (claude) | Avoided by construction — system-prompt append beats context-level `CLAUDE.md` even without special wording | §1, VERIFIED 2/2 |
| Repo `CLAUDE.md` silently truncated when read via `project_doc_fallback_filenames` | Avoided only by also raising `project_doc_max_bytes`, or better, by using the inline-into-global approach instead, which has no known cap | §2, §3, VERIFIED |
| `AGENTS.md` written into repo, leaking to human's own codex sessions / other agents in the worktree | Avoided — sb's design never writes into the repo at all | §6, VERIFIED |
| Private `CODEX_HOME` config affecting the human's real `~/.codex/config.toml` | Avoided — config is per-agent, confirmed no bleed into the real file | §6, VERIFIED |
| Private `CODEX_HOME` silently dropping the user's real `~/.codex/AGENTS.md` globals | **Not avoided** unless sb explicitly reads and inlines it — currently a real, if presently inert (file is empty), regression | §5, VERIFIED mechanism |
| Nested subdirectory `AGENTS.md`/`CLAUDE.md` silently shadowing the repo root doc sb expects to be in force | Depends entirely on where sb sets cwd; not itself an sb bug, but worth sb being deliberate about cwd | §4, VERIFIED |
| codex `exec` blocking forever waiting on stdin when driven non-interactively without `< /dev/null` | Not a layering issue but a real operational trap hit repeatedly while building this probe — worth a note for whoever writes the codex spawn code | discovered directly this round |

## What's still open / unverified

- True ceiling (if any) for the `CODEX_HOME/AGENTS.md` global-doc size — untruncated to
  60KB tested, not pushed further.
- Nesting three or more directories deep, or with docs present at every level
  simultaneously — only root-vs-immediate-child-with/without-own-doc was tested.
- `~/.claude/CLAUDE.md` global-doc *content* merging, and `~/.codex/AGENTS.md` global-doc
  *content* merging when `CODEX_HOME` is left at its default — both real files are empty
  on this machine and the task disallows writing to them, so only the generic mechanism
  (proven via scratch stand-ins) is verified, not the specific real files.
- Whether the precedence-inversion result (§1) is stable across different codex models/
  reasoning-effort settings — all trials ran against this machine's configured default
  model; not varied deliberately.
- Whether an sb-spawned claude agent's behavior in a real herdr pane (rather than a bare
  `claude -p` invocation) differs in any way — the claude trials in §1/§5 used the plain
  CLI directly, not a live `sb`/herdr-spawned pane, to avoid disturbing the fleet; the
  flags matched what `herdr.py` actually sends, but this is one level removed from a real
  spawn.

## Cleanup performed

- Deleted both scratch trees (`.../scratchpad/layering/`, `.../scratchpad/layering2/`)
  in full, including their private `CODEX_HOME` dirs (config, `AGENTS.md`, copied
  `auth.json`, and all session/rollout files created during every trial) and both scratch
  git repos.
- Confirmed via `ps aux | grep codex` that no `codex exec` process was left running.
- Confirmed via `grep -i layering ~/.codex/config.toml` (no match) that the real config
  was never written to.
- Confirmed via `find <worktree root> -maxdepth 1 -iname AGENTS.md -o -iname CLAUDE.md`
  (empty) that no stray file was left in the real switchboard checkout.
- Did not touch `~/.codex/AGENTS.md` or anything under `~/.claude/` (both read-only
  checked, confirmed still empty, never written to).
