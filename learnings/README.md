# learnings — notes from the session of 2026-08-14

Everything in this folder was written during one working session on 2026-08-14. Each note
lived only on the branch of the agent that wrote it and would have been lost when that
branch was; they are collected here **unedited**. Where a note was later contradicted or
overtaken, this README says so — the note itself has not been touched.

Nothing here is trusted the way `DESIGN-TRUTH.md` is. These are investigations, proposals
and reviews: read them for the evidence and the reasoning, not as settled design. Where a
conclusion did become settled design, it is in `DESIGN-TRUTH.md` and that is the version
that counts.

Note names are the author's own. The agent that wrote each one is given below.

---

## Worktrees, spaces, and how herdr groups them

**`worktree-per-level.md`** (researcher-39) — *Does every agent get its own worktree?*
Andrew doubted the design document, having watched what looked like a worktree per agent.
The answer is no: only a dispatcher's children fork a worktree; below that, a lead's
children are tabs sharing the lead's worktree and branch. Checked in the code and then
proved live — a lead and its two workers came out on the same workspace, branch and
directory. The reason it looked otherwise is that everything Andrew had watched was
spawned by a top, which forks per child under either model. **Still stands, and it is now
a settled entry in `DESIGN-TRUTH.md`** (confirmed 2026-08-14); this note is the evidence
behind it.

**`researcher-37-why-so-many-worktrees.md`** (researcher-37) — *Why does switchboard make
so many worktrees?* Same rule, reached independently: the fork happens only on the `is_top`
stamp, and `sb cleanup` never removes a worktree or a branch. Still stands. The cleanup
half of it became GitHub issue #40 (see the issue notes below).

**`board-worktree-grouping.md`** (researcher-32) — *Could the board show worktree
boundaries?* Found that agents in one workspace are already contiguous on the board and
already separated by the existing blank-line rule, so ordering and grouping were done; only
an explicit indicator was missing, and in the common case it would be noise. Still stands.
The indicator was later prototyped as the "workspace gutter" in the board mockup.

**`herdr-space-assignment.md`** (researcher-16) — *How does a herdr space get assigned?*
An early read of the switchboard side: spaces are only ever created, never attached to,
and every fork uses the repo's own directory as `--cwd`. **Partly superseded.** Its
switchboard-side facts hold, but it guessed at herdr's grouping behaviour rather than
reading herdr, and it ends by saying so. `herdr-grouping-capability.md`,
`auto-create-space.md` and `dispatcher-home-and-space.md` read the herdr source and settle
what it left open.

**`recruiting-space-followup.md`** (researcher-17) — *Why didn't the recruiting agent land
in the `recruiting` space?* Because `--workspace` only joins workspaces switchboard already
knows about, and that repo had never been `sb init`'d, so the agent forked a worktree of
*this* repo instead. The diagnosis stands and is the origin of the DESIGN-TRUTH entry that
cross-repo work is a question, not a spawn. Its speculation about herdr grouping was
checked and confirmed by `herdr-grouping-capability.md`.

**`herdr-grouping-capability.md`** (researcher-18) — *Can herdr group agents under
something other than the repo?* No. Read against herdr's own source: a worktree's parent
workspace is resolved by git repo identity and there is no create-time or after-the-fact
way to place it elsewhere. Still stands.

**`auto-create-space.md`** (researcher-28) — *Could switchboard create or attach a space
per dispatcher automatically?* Found that herdr has no persisted space record at all —
grouping is a runtime effect of the git common dir — so the shape Andrew described needs
either one clone per task or a small change inside herdr. **Partly superseded:** Andrew
later chose neither, and `DESIGN-TRUTH.md` now records the muddled-view outcome as a known
limitation rather than pending work. The mechanics in the note are still accurate. It also
notes it could not find the prior grouping note in its own worktree and re-derived
everything, which is why it overlaps `herdr-grouping-capability.md`.

**`dispatcher-home-and-space.md`** (researcher-29) — *Why does a dispatcher get its own
space, and what is its home?* Corrected the premise everyone had been working from: herdr
does not recompute repo grouping per render, it reads a persisted `worktree_space` field
that only the worktree-create/open path ever stamps. A dispatcher's plain workspace-create
never stamps it. Still stands.

**`dispatcher-space-and-cross-repo.md`** (worker-27) — *Can a dispatcher be adopted as a
repo's group parent?* Yes, and it was reproduced live in an isolated clone: herdr adopts
the first already-open workspace matching the repo, and a dispatcher's home qualifies.
Still stands, and it is the evidence behind the "where that model can bend" entry in
`DESIGN-TRUTH.md`. This is the one note here that had already reached `main` on its own —
the same file is at `notes/dispatcher-space-and-cross-repo.md`.

## The dispatcher / lead split

**`scout-naming-report.md`** (researcher-13) — *How does switchboard name agents and
workspaces?* Names come from configurable vocabulary settings, not string literals, so a
repo can already rename `main` and the roles without a code change; agent numbers never
reset because the name counter probes history rather than counting live agents. Still
stands.

**`top-orchestrator-role.md`** (researcher-19) — *Why does a top orchestrator drift into
doing the work itself?* Because the `is_top` stamp only decides where an agent's children
land and says nothing about what the agent may do, and there was one orchestrator prompt
for every depth. Diagnosis and proposal only. **Overtaken by events, in the good sense:**
the split it argued for was built and merged, and `DESIGN-TRUTH.md` now carries dispatcher
and lead as two roles with two prompts.

**`role-vocabulary.md`** (researcher-21) — *What should the two halves be called?* The
companion proposal to the note above, on naming and on which behaviours belong to which
role. Also overtaken by the shipped split: the names chosen were `dispatcher` and `lead`,
with `orchestrator` kept only as a config alias.

## The board UI

Five research notes and two mockup notes, all from the same effort to make `sb board`
richer. None of this shipped — the mockup is a spike in `scripts/board_mockup.py` on the
`worker-25`/`worker-28` branches, wired into nothing.

**`board-ui-current.md`** (researcher-24) — what the board is today: two independent
renderers over one snapshot, the collector/panel data path, and the invariants the drawing
code rests on. Still accurate.

**`board-inventory.md`** (researcher-30) — an element-by-element and field-by-field
inventory of both renderers, with no design opinions. Still accurate.

**`board-ui-techniques.md`** (researcher-25) — terminal rendering techniques available,
and the constraints any of them has to respect (stdlib-only today, redraw-in-place,
hand-rolled mouse and character-width handling).

**`board-ui-deps.md`** (researcher-26) — a deep comparison of `rich`, `textual`,
`blessed`, `urwid` and `prompt_toolkit`, including width-measurement code the author
actually ran. Snapshot dated 2026-08-14; versions and star counts will drift. `rich` was
the pick, and the mockup used it.

**`board-ui-looks.md`** (researcher-27) — what the board could look like within a 40–60
column pane, as sketches rather than libraries.

**`board-mockup.md`** (worker-25) and **`board-mockup-worker-28.md`** (worker-28) — the
same document at two points: worker-25 wrote it for the first runnable mockup, worker-28
revised it a little while continuing the work. Read worker-28's version if you only read
one.

**`board-mockup-nogaps.md`** (worker-28) — eight rounds of revisions to the mockup, with
frames for each. Read it back to front: the note says outright that only the round 8 frames
show the current state, and every earlier round is superseded by a later one.

**`verify-bracket.md`** (qa-2) — *Does the workspace bracket in the mockup appear for
agents genuinely sharing a worktree?* Yes, proved on a live fleet in an isolated clone with
two real multi-agent worktrees. Still stands, for the mockup as of `worker-28` @ `2f0c05b`.

## Blocking, and what agents put in front of a human

**`block-message-examples.md`** (researcher-34) — real pre-`sb block` messages recovered
from Claude Code transcripts, checked against the format rule. Also documents how to find
an agent's transcript, and the honest caveat that a transcript carries no agent name, so
attribution is inferred from the worktree directory.

**`block-message-bloat.md`** (researcher-35) — Andrew judged even the good examples too
long. This note goes back to three full transcripts, marks what is deletable, and rewrites
each shorter. **Read with the critique below**: one of the three rewrites was later found
to have changed the meaning.

**`rewrite-critique.md`** (reviewer-19) — a hostile read of those three rewrites. Its
headline finding supersedes the framing of the note above: character count is a proxy that
can be gamed, the rewrite that cut the most is the one that changed what Andrew would be
agreeing to, and nobody had checked the rewrites against the originals for meaning.

**`block-guidelines-audit.md`** (researcher-36) — *What in our own prompt text produces
bloated human-facing output?* Traces exactly what a spawned agent receives, and finds
instructions like "restate what you were asked" repeated at least seven times across
protocol, roles and presets. Still stands as an audit; no prompt trimming has been done
against it.

**`info-design-research.md`** (researcher-38) — outside research (Nielsen Norman and
others, with real sources) on how a decision request should be shaped for someone who is
scanning rather than reading. Background for the above; nothing in it was applied yet.

## Lifecycle and reliability

**`gone-agents.md`** (researcher-31) — *Why is clearing a dead pane manual?* Mostly it is
not: absence is already confirmed, written to the store, and reported to the parent
automatically. The one genuinely manual step is `sb cleanup`, deliberately so, because it
is the one irreversible action. Still stands.

**`stuck-agent-interrupt.md`** (researcher-33) — *Why didn't `sb tell --interrupt` free
two agents stuck on Claude Code's auto-mode dialog?* Because the escape keystroke lands but
the follow-up message is delivered by an unconfirmed single prompt call, which the dialog
silently swallows. The note decompiles the dialog's gating logic and shows it re-arms every
7 days for every session on the machine, so this is not a one-off. It is careful about what
it did and did not prove — it never reproduced the literal dialog end to end. Nothing has
been fixed against it.

## Reviews of the dispatcher/lead branch

Three independent reviews of `worker-30-review`, the branch that split the orchestrator
role. **All three are now historical**: their findings were fixed and the branch merged as
pull request #39 (commits `a1d964d`, `d63a0a5`, `4bc54d5` on `main`).

**`reviewer-16-dispatcher-lead-landing.md`** — judged as a change landing on a running
fleet. Found that `sb start` would stop seeing the top-level agents currently running,
because it looked them up by role name rather than by the stamp. Fixed in `a1d964d`.

**`reviewer-18-worker-30-review-code-and-tests.md`** — read cold as code and configuration.
Found that the role alias and the fallback role were read from the shipped settings only,
so a repo could not configure either. Fixed in `d63a0a5`.

**`reviewer-17-design-truth-round3.md`** — checked the rewritten `DESIGN-TRUTH.md` sentence
by sentence against the code. Found three false sentences, one missing open question, and
that the rewrite had invalidated most of the code's line-number citations into the
document. Fixed in `4bc54d5`, which is also where the citation test came from.

## Issues filed

**`issue-worktrees-never-deleted.md`** and **`issue-worktree-granularity.md`** (worker-28)
— the bodies as filed for GitHub issues **#40** (bug: worktrees are never deleted, 102 of
them and 536 MB at the time of measuring, contradicting the `DESIGN-TRUTH.md` entry that
cleanup deletes them) and **#41** (question: is one worktree per top-level delegate the
right granularity). Both were still open when this folder was assembled.

**`issue-filing-commands.md`** (worker-28) — the record of filing them, including that the
first attempt was refused and permission was asked for rather than routed around. Purely
historical.

## Not about switchboard

**`researcher-15-quant-gap.md`** (researcher-15) — a research task Andrew ran in the same
session about quant and systematic hedge funds hiring new-grad engineers, with output
written to a separate `recruiting` repo. It has nothing to do with switchboard and is kept
only because it would otherwise have been lost with its branch.
