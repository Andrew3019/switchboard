# The top-orchestrator role: diagnosis and a proposal

Written by researcher-19, design/diagnosis only. No source files touched in this pass.

## 1. Diagnosis: why a top orchestrator drifts into doing the work

**One-line cause.** The `is_top` stamp (`switchboard/store.py:158-183`, set only in
`Broker._top`, `switchboard/broker.py:1012-1020`) decides exactly one thing — whether *this
agent's children* get a fresh worktree or a tab (`Broker.mints_space`,
`switchboard/broker.py:2581-2598`, "THE FORK RULE" at `broker.py:3069-3104`). It decides
nothing about what the top *itself* may do. Nothing else in the code or the prompt does
either, so when Andrew hands a task straight to a freshly-started top, it is just an
`orchestrator`-role agent with every tool live, sitting in his own main checkout, and
"delegate instead of doing it" is a preference it can talk itself out of — not a rule it
can't get around.

**The prompt is deliberately scope-blind.** There is one orchestrator role file,
`defaults/roles/orchestrator.md`, used at every depth. Its own header comment says so
outright (`orchestrator.md:6-14`): *"THE orchestrator role — there is only one, deliberately
... the only difference between the top one and the deepest one is scope, and scope is
already told to it at spawn."* The prompt body never branches on top-vs-nested; the closest
thing to a rule is generic and applies identically everywhere: *"Do not do the work
yourself, even when it looks quicker"* (`orchestrator.md:159`), sitting a few lines below
*"a glance at one or two files to place yourself is fine"* (`orchestrator.md:138-139`) — and
"just placing myself" is exactly the gap a model rationalises a quick answer through.

**The spawn-time prompt assembly confirms there is no top-only fragment.**
`Broker.delegate()` builds the system prompt as an ordered list
(`switchboard/broker.py:3113-3133`): protocol, identity, role list, then — only if a
workspace is set — the `workspace` fragment (`defaults/prompts.toml:60-66`), then the role's
own prompt. There is no `if is_top:` branch anywhere in that list. `defaults/prompts.toml`
has `[spawn] identity`, `roles`, `workspace`, `start_task` — no `top`.

**The top's own workspace *is* Andrew's main checkout, not a worktree.** `Broker._top`
calls `self.delegate(first, role=MAIN, ..., workspace=name, cwd=str(self.repo), ...,
is_top=True)` (`broker.py:1017-1020`) — `cwd` is `self.repo`, the checkout `sb start` was
run in. The design comment says *"a top-level orchestrator does no writes"*
(`broker.py:882-884`), but that is an assumption stated in a comment, never enforced. If a
top uses Edit/Write/Bash on a task handed to it directly, it is editing files straight on
Andrew's own checkout and branch, uncommitted, with no worktree isolation at all — the
single worst place in the whole system for that to happen.

**There is no tool-layer restriction anywhere in the codebase**, confirmed by a second,
independent read of the source (spawned in parallel, see below): every spawned agent gets
the same tools, gated only by one global `PERMISSION_MODE` setting
(`switchboard/herdr.py:38,557`), regardless of role or `is_top`. The one real precedent for
"a verb refused in code, not just by prompt" is `Broker._refuse_bare_delegate`
(`broker.py:693-718`), which reads a boolean field on the caller's *role*
(`Role.delegate`, `switchboard/roles.py:41`) before letting `sb delegate` proceed, and
`sb start`'s own human-only refusal at `switchboard/cli.py:801-812`. Both are real
precedent for "refuse in the one chokepoint every call goes through," but neither covers
Edit/Write/Bash — those are Claude Code's own tools, not `sb` verbs, so nothing in `switchboard`
today looks at them at all.

**This gap was already named and half-closed once, for the wrong half.**
`DESIGN-TRUTH.md:173-174`: *"Top and workspace orchestrators must be clearly
differentiated, and some mechanism other than the prompt must make that true as well."*
— confirmed 2026-08-09. `DESIGN-TRUTH.md:342-345` (Open/undecided) says this was "answered"
by the `is_top` stamp. It was answered for the meaning "where do my children go" —
that is real, and it works. It was never separately answered for the meaning Andrew is
raising now: "what may I do myself." Those are two different questions that happen to share
one English sentence, and only the first one got a mechanism.

## 2. The proposed rule

**A top orchestrator (`is_top=1`) may:** talk (`sb tell`, `sb block`, `sb done`), spawn and
manage children (`sb delegate`, `sb start`, `sb status`, `sb cleanup`), name its own task
and thereby its worktree/branch/identity, and glance — read a file, run `sb status`,
`sb board` — to place itself. **It must not:** edit or write any file, or run a command that
changes repo or task state, no matter how small the task looks or how confident it is —
every task, including a one-line factual question, gets a child.

**Enforcement, three layers, because a prompt alone is what has already failed:**

1. **A top-only prompt fragment** (new `[spawn] top` entry, appended only when
   `is_top` is true) stating the rule in plain words, the same place the `workspace`
   fragment already lives conditionally. Necessary for the agent to understand *why*, but
   — per Andrew's ask — not sufficient on its own; this is the layer that failed before.
2. **A tool-layer refusal**, via a new `PreToolUse` hook (the codebase already has the
   `UserPromptSubmit`/`Stop` hook infrastructure in `switchboard/hooks.py` and
   `hooks.settings_file()`, `hooks.py:91-162`, plus `bin/sb-stop-hook` as the pattern to
   follow). It resolves the calling agent the same way `hooks._agent_row` already does
   (`hooks.py:181-200`), and if that agent's row has `is_top=1` and the tool is
   `Edit`/`Write`/`NotebookEdit`, it denies the call. This is what actually bites: it does
   not depend on the model choosing correctly.
3. **`sb delegate`/`sb start` already refuse the wrong direction** (bare agents can't
   spawn, only a human can `sb start`) — no change needed there; the new gap is entirely
   about what the top does with tools it already holds, not about who it can spawn.

Bash is the deliberately unresolved piece — see the change list, item 3.

## 3. Edge cases

1. **Human asks a one-line factual question.** *Delegate.* Andrew's own framing rule 2 is
   explicit: even a quick question goes to a child, so follow-ups continue with that child
   at full context. Answering directly is the leak this proposal exists to close — it is the
   easiest case to rationalise around, so it cannot be the one exception.

2. **Human asks it to run a command / check status / clean up.** *Allow — but split the
   verb from its purpose.* `sb status`, `sb board`, `sb cleanup` are the top's own job
   already (nothing about them touches the task or the repo) and stay allowed under the
   `PreToolUse` gate as-is (only Edit/Write/NotebookEdit are denied). A command that
   inspects or changes the *task's* state — running the app, grepping the codebase for an
   answer, editing a config — is doing the work, and gets delegated like anything else.

3. **A child needs a decision only the human can make.** *The child blocks the human
   directly; the top does nothing.* This is already how the system works — a parent is
   never told a child blocked (`DESIGN-TRUTH.md:266-267`), the board surfaces it, and the
   orchestrator role already names "do not become a permanent proxy" as a failure mode
   (`orchestrator.md:213-215`). No new mechanism needed; the top-only fragment should just
   not contradict it.

4. **Human keeps talking to the top about a task a child now owns.** *Allow-with-a-nudge.*
   The top should redirect — name the child, point at it — rather than either refusing to
   answer or quietly re-absorbing the thread. This can only be prompt guidance; nothing at
   the tool layer can tell "answering a question" from "relaying a child's work" apart.
   Flagged as the weakest-enforced case in this whole proposal.

5. **The task is genuinely trivial (a one-line edit) — is a whole worktree justified?**
   *Allow, no special case.* The fork rule is already role-agnostic and deliberately so —
   *"'it will not write' is a claim about the future"* (`broker.py:3069-3084`) — and a
   worktree is cheap and disposable (`sb cleanup` deletes it, `restore` exists until then).
   Carving out an exception for "small" tasks reopens exactly the hole this proposal closes:
   it is always the small task that looked safe enough to do directly.

6. **Naming collisions.** *Allow, already enforced, needs one added instruction.* Collision
   handling is already fail-closed in code — `BranchTaken` (`broker.py:2943-2944`) and the
   `_name_held_by == "bare"` refusal (`broker.py:2934-2942`) — so a top that picks a taken
   name gets a clear error, not a silent overwrite. The one gap is that nothing tells the
   top what to do next; add one sentence to the new top-only fragment pointing at the same
   pattern `_unique_name` already uses for delegate auto-naming (`broker.py:3329-3333`):
   on collision, try `<name>-2`, etc.

7. **A top that has nonetheless accumulated context.** *Not recoverable — starting fresh
   is the answer, and that is fine, because Andrew's rule 5 already says existing tops are
   left alone.* Nothing about this proposal needs a contaminated top to self-correct; going
   forward, the tool-layer gate stops new ones from accumulating it in the first place.
   One open question, flagged rather than answered: does a hook edit reach an *already
   running* Claude session (its settings file was read once at spawn), or only new spawns?
   If only new spawns, that is consistent with "leave existing tops alone" and needs no fix;
   if it silently reaches live sessions too, that is a bonus, not a requirement. Not
   verified — flagged for whoever implements this to check before relying on it either way.

8. **What does a top's own `sb done` even mean, if it never did work?** *It mostly doesn't
   apply, and that's already the design.* DESIGN-TRUTH already says the top "is just idle...
   it persists until Andrew closes it" and Andrew never calls lifecycle commands himself
   other than `sb start` — there is no automated parent reading a top's `sb done`. If a top
   ever does call it, it should read as a delegation receipt ("handed off to X, which
   reported/blocked") rather than a work summary — but this is not a case that needs new
   enforcement, just a sentence in the fragment so an agent doesn't invent a false
   obligation to summarise work it never did.

## 4. Change list

1. **`defaults/prompts.toml`** — add `[spawn] top`, a new fragment parallel to the existing
   `workspace` one (`prompts.toml:51-66`): states the top-only rule (must delegate
   everything including one-liners; may look at `sb status`/`sb board`/one file to orient;
   naming your own task/workspace is expected; on a name collision try `<name>-2`; a `done`
   from you, if you ever call it, is a delegation receipt not a work summary). ~15-20 lines
   including the header comment this file's convention expects. Single line once flattened,
   per the file's own rule.

2. **`switchboard/broker.py`, `Broker.delegate()`** (~`broker.py:3113-3133`) — thread
   `is_top` into the prompt list: `if is_top: prompts.append(self._say("spawn.top"))`,
   placed after the `workspace` fragment and before the role's own prompt (same ordering
   logic as `workspace`: information the agent needs before it reads the role text that acts
   on it). ~3 lines.

3. **`switchboard/hooks.py`** — the real enforcement. Add a `PreToolUse` entry to the JSON
   `settings_file()` writes (near `UserPromptSubmit`/`Stop`, `hooks.py:116-153`), pointing at
   a new `bin/sb-pretool-hook`. Add a `pretool_gate(payload, db)` function following the
   `stop_gate` pattern: resolve the caller via the existing `_agent_row` helper
   (`hooks.py:181-200`), read `is_top` off that row, and if true and the tool name is one of
   `Edit`/`Write`/`NotebookEdit`, return a deny decision; otherwise fail open exactly like
   every other hook in this file (unresolvable caller, DB error, or non-top agent → no
   opinion). ~60-90 new lines in `hooks.py`, plus a ~30-line `bin/sb-pretool-hook` mirroring
   `bin/sb-stop-hook`'s shape (stdin → JSON, always exit 0, decision travels in the JSON).
   **Not confident about:** the exact JSON field names/values Claude Code expects for a
   `PreToolUse` deny decision — there is no existing `PreToolUse` hook in this codebase to
   confirm the contract against, so this needs verifying against Claude Code's current hook
   schema before shipping, not assumed from the `Stop`/`UserPromptSubmit` shape alone.

4. **Bash — deliberately left open, flagged rather than guessed at.** Edit/Write/NotebookEdit
   cover direct file mutation cleanly with no false positives. Bash can still write files
   (`cat >`, `sed -i`, `git commit`) and also carries the top's own legitimate traffic —
   `sb delegate` itself runs through the Bash tool, so a blanket Bash deny breaks the top's
   real job. Recommend shipping items 1-3 first (they close the sharpest risk — direct
   file edits on Andrew's own checkout) and treating a Bash allowlist (`sb `/`git status`/
   read-only prefixes allowed, everything else denied) as a deliberate fast-follow once
   real top-orchestrator Bash traffic is known, rather than guessing an allowlist now and
   breaking the top's own delegation calls.

5. **No change to `defaults/roles/orchestrator.md`.** The single merged role/prompt design
   is a deliberate, already-confirmed decision (`orchestrator.md:6-14`) and this proposal
   does not reopen it — scope (including top-ness) stays something told to the agent at
   spawn, not baked into a second role.

6. **Tests** — `tests/test_config.py` (or a new `tests/test_hooks.py`): assert the `top`
   fragment appears in the prompt list iff `is_top=True`; assert `pretool_gate` denies
   `Edit` for an `is_top` row and allows it for a non-top row and for an unresolvable
   caller. 2-3 small cases, following the existing `test_config.py:171-186` pattern for
   prompt-fragment tests.

7. **`DESIGN-TRUTH.md`** — if Andrew confirms this proposal, it needs a new entry under
   "Orchestrators" recording the top-only restriction and that enforcement is a
   `PreToolUse` hook plus a spawn-time fragment, not the prompt alone — and, per this file's
   own rule, a full re-read pass afterward to keep it consistent (the existing
   "Open/undecided" note that the differentiation question was "answered" by the `is_top`
   stamp would need narrowing, since that stamp answers routing, not this). Not done in this
   pass — only Andrew adds entries.
