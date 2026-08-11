# Settling 3.1's open question: does `agent prompt` interleave or queue?

Run 2026-08-11, 01:43–01:52 local, read-only probe. Nothing in this repo was changed by
the experiment; this document is the only artifact.

**Headline answer.** Against a genuine single long-running tool call (not the multi-step
turn the earlier docstring test used), `agent prompt` does **not** interleave mid-tool-call
and does **not** cancel anything. It queues the text and it is delivered to the model at
the *next tool-call boundary* — the instant the in-flight tool call returns and the model
is about to decide what to do next — not mid-call, and not held until the whole session
goes fully idle. That is materially closer to DESIGN-TRUTH's "queued... delivered on the
next turn" than to `Herdr.prompt()`'s own docstring ("This INTERLEAVES. It does not
queue.") or `_ring`'s comment (`broker.py:4150-4153`), both of which are contradicted by
this test. See "Reconciling the contradiction" below for why the earlier test likely got a
different-looking result from the same underlying mechanism.

## Where and how

Isolated `git clone` of this repo at `main` tip `5998a43`, into
`/private/tmp/.../scratchpad/probe31-clone`, driven throughout by that clone's own
`./bin/sb` (`sb doctor` confirmed a store at `<clone>/.git/agentflow/state.db` and no
collector ever running — I passed `--no-board` on every spawn, so no panel/collector
process was ever started for this probe). The live fleet's `sb`/store was never touched;
I never ran the clone's binaries from outside the clone.

Three trials, one subject agent each (`subject-a`, `subject-b`, `subject-c`, spawned with
`sb start --name <x> --no-board "Read audit/probe31/subject-task-*.md and follow it
exactly."`, cleaned up with `sb cleanup <x>` immediately after each). Each subject's task
(`audit/probe31/subject-task-*.md` in the clone, not committed — scratch, torn down with
the clone) was: run `for i in $(seq 1 90); do date +%H:%M:%S.%N >> <logfile>; sleep 1;
done` as **one single Bash tool call**, and the moment any text becomes visible mid-call,
note the wall-clock time and exactly how it appeared, before acting on it. The `<logfile>`
lives under `/tmp` (shared with the host, outside the clone), so I could watch it fill in
real time from outside the agent to know precisely when the tool call started, how far
into it I was sending, and when it actually finished — independent of anything the agent
self-reports.

Trials 1 and 2 sent via the raw primitive `_ring` uses: `herdr agent prompt <name>
"<text>"` directly (bypassing `sb`/`broker.py` entirely — no `_busy()` gate in the path at
all). Trial 3 sent via `herdr pane send-text <pane> "<text>"` + `herdr pane send-keys
<pane> enter` — literal keystrokes into the pane's terminal, the closest thing available
to simulating a human typing, to test BUILD-PLAN's suspicion that DESIGN-TRUTH might
describe the human-typed path rather than the API call.

## The three trials

| | trial 1 — `agent prompt` | trial 2 — `agent prompt` | trial 3 — `pane send-text`+enter |
|---|---|---|---|
| loop started | 01:43:36 | 01:46:53 | 01:50:35 |
| sent | 01:43:48.38 (~12s in) | 01:47:03.05 (~10s in) | 01:50:42.83 (~10s in) |
| loop's own last log line | 01:45:08 (90/90 lines) | 01:48:24.12 (90/90) | 01:52:05 (90/90) |
| did the tool call get cancelled? | no — ran to full 90/90 | no — ran to full 90/90 | no — ran to full 90/90 |
| agent's own account of when it saw the text | "surfaced attached to the Bash tool result... only after the 90-second command completed — I had no awareness of it while the tool call was running" | "arrived attached to the Bash call's result... Not visible to me at any point while the command was still executing" | "arrived as a separate system-reminder-style block delivered immediately after the long Bash call returned... I had no awareness of it during the 90 seconds" |
| landed mid-call or at the boundary? | boundary, after | boundary, after | boundary, after |

All three subjects reported `sb done` with a correct account of the full 90-line loop
(`sb inspect subject-a/b/c` summaries confirm the timestamps against the independently
observed `/tmp` log files, which is the authority here, not the agent's self-report alone).

## What this settles

- **`agent prompt` does not interleave mid-tool-call.** Zero of three trials showed any
  awareness, action, or output change during the running command — I was watching the log
  file fill in real time from outside the agent the whole time, and it never paused,
  skipped a beat, or terminated early.
- **`agent prompt` does not cancel work**, unlike `sb interrupt` (which sends `esc` first —
  see `audit/delivery-modes.md`, trial 1, where the interrupted subject visibly abandoned
  its in-progress file list). All three loops here ran their full 90 seconds.
- **The message queues and is delivered at the very next point the model can act** — the
  instant the in-flight tool call's result comes back, before the model decides what to do
  next. Not mid-call, and — this is the part that differs from `sb tell`'s current
  busy-gate — not held until the entire agentic turn/session goes idle either. (Compare
  `audit/delivery-modes.md`'s busy-`tell` trial: 5 min 37 s, because `_ring`'s `_busy()`
  check refuses to call `self.h.prompt` at all until herdr reports the agent fully idle. That
  wait is `_ring`'s own policy, not a property of the underlying `agent prompt` call — this
  probe called `agent prompt` directly, skipping that gate entirely, and got sub-tool-call
  delivery instead.)
- **I could not distinguish the human-typed path from the `agent prompt` API path.** Trial
  3 (literal keystrokes via `pane send-text` + `send-keys enter`) behaved identically to
  trials 1–2 in every respect that could be measured: no mid-call awareness, no
  cancellation, delivery at the same tool-call boundary. Said plainly, per the brief: I
  looked for a difference and did not find one in this test. I cannot rule out a difference
  under other conditions (see "What I did not test").

## Reconciling the contradiction with the existing docstring/comment

`Herdr.prompt()`'s docstring (`herdr.py:480-494`) and `_ring`'s comment
(`broker.py:4150-4153`) both say `agent prompt` "INTERLEAVES... injecting into the current
turn rather than queueing after it," citing a poke "handled at +13s" while a task "did not
complete until +63s." That is consistent with my data in one specific way and inconsistent
in the way that matters: **it is entirely explainable as delivery-at-the-next-boundary**,
if that earlier "60-second multi-step turn" was built from several shorter tool calls
rather than one continuous one — the poke would then land at whichever short boundary came
next after it was sent, which could easily be +13s into a task whose *other* steps kept
running until +63s. Nothing in that account rules out "queues, delivered at next boundary"
in favor of "injects mid-call" — it just didn't test a single long call, which is the one
shape that can tell the two apart, and which this probe used specifically because of that
gap. I did not have access to whatever produced the original +13s/+63s numbers to re-run
it directly, so I can't say for certain that's what happened there — but three-for-three
against the shape of test that actually distinguishes the two explanations, all landing at
the boundary and never mid-call, is enough that I'd treat "INTERLEAVES, does not queue" as
unsupported rather than confirmed, and DESIGN-TRUTH's "queued... delivered on the next
turn" as the better description of what `agent prompt` actually does.

## What building "next turn" would take

BUILD-PLAN's pass test for 3.1's default mode: *"a `tell` to a busy agent lands at its
next step boundary with the in-flight tool call completing."* That is exactly the
behaviour this probe measured from the raw primitive, three times, with no code changes
at all. So the primitive already does what "next turn" needs — the gap is entirely in
`broker.py`'s `_ring`, which currently never calls `self.h.prompt` on a busy agent unless
`force=True`, and `force=True` today only exists wired to `interrupt`'s escape-key +
cancel-wrapper path.

**Sketch (not built, not sized in code — this is a read-only probe).**

1. Give `_ring` a delivery-mode argument (or a third boolean alongside `force`/`answer`)
   that, for "next turn", calls `self.h.prompt(who, text)` unconditionally like `force=True`
   does today, but **skips** the `self.h.interrupt`/escape-key call and the
   `notify.interrupt` cancel-wrapper template — i.e., reuses the forced-ring branch of
   `_ring` (`broker.py:4204` on) verbatim, just entered from a path that never sends `esc`
   and never wraps the text as a cancellation.
2. `cli.py:155-158` (`sb tell`'s parser) needs a way to choose the mode — a flag
   (`--when-idle`, `--interrupt`) with "next turn" as the new default, replacing today's
   only mode (when-idle) as default. 3.2 (delete `sb interrupt`) becomes: route its
   capability through this same `_ring` with `force=True` *and* the escape/cancel wrapper,
   as today, just reached via `tell --interrupt` instead of a separate verb.
3. `defaults/prompts.toml`'s `[notify]` block needs a plain, non-cancelling wrapper
   template distinct from `notify.interrupt`, for whatever text (if any) "next turn"
   prepends — this is also where 3.3's `[sb: from <name>]` tag belongs, so these two land
   together as BUILD-PLAN's run-order already says.
4. Role/protocol docs need one sentence correcting the "queued and delivered next turn"
   framing to be specific about *tool-call* boundary, not full-turn boundary, since that
   is what was actually measured — worth stating precisely so a future reader doesn't
   re-litigate this.

**Rough size.** Small-to-medium, not "large, unsized" as BUILD-PLAN currently has it —
the hard unknown BUILD-PLAN was gated on (does the primitive support this at all) is now
answered yes, so what's left is mode plumbing through code that already has a `force`
branch to reuse, plus the CLI surface and prompt text. The uncertainty that's left: multi-
message ordering and queue depth while busy were not tested here (see below) — if herdr
drops or reorders a second `agent prompt` sent before the first is consumed, that changes
the size. Worth a follow-up probe before this is scoped further, not before it is decided.

## Is DESIGN-TRUTH's queueing behaviour reachable at all?

Yes, as measured: `agent prompt`, sent directly, already produces "queued, delivered at
the next point the model can act." What does not exist today is a *product surface* for
it — `sb tell` never reaches this behavior because `_ring`'s busy-gate intercepts every
non-forced call before `self.h.prompt` is ever invoked, and the only forced path
(`force=True`) is currently reachable solely through `sb interrupt`, which always adds the
escape key and cancel wrapper on top. So the queueing DESIGN-TRUTH describes is not a
missing *capability* — it's a missing *route to the capability the CLI already has under
its feet*.

## What I did not test

- **Multiple messages queued behind one busy agent.** Each trial sent exactly one message.
  Whether a second `agent prompt` sent before the first is consumed by the model arrives in
  order, coalesces, or drops is untested and directly affects 3.1's size (see above).
- **A tool call inside a subagent (`Task` tool) or a very short tool call.** All three
  trials used one 90-second `Bash` call chosen specifically to give a wide, unambiguous
  window. Whether the same boundary-delivery holds for a tool call measured in
  milliseconds, or for a nested subagent's own tool calls, is untested.
- **Sending while the agent is `blocked`, not just busy.** All three subjects were mid-task,
  never blocked. `_ring`'s blocked-gate is a separate check from the busy-gate this probe
  bypassed, and this probe never touched it.
- **The human-typed path under conditions where it might diverge** — e.g. typing
  interactively at natural human speed with pauses, versus this probe's send-text-then-
  enter which lands as fast as trial 1/2's API call. If Claude Code's queueing keys off
  something time-sensitive (a debounce, a "still typing" state) that a fast synthetic paste
  doesn't trigger, that would not show up here. What this probe does say with confidence:
  the *mechanism* — pane keystrokes vs. the `agent prompt` socket call — produced
  indistinguishable results when both are delivered essentially instantly.
- **Whether `agent prompt`'s behavior changes on a longer-running, more realistic multi-tool
  turn** (the exact shape the original docstring test used) — I did not have that original
  test's setup to re-run head-to-head against this one; "Reconciling the contradiction"
  above is an inference from the mechanism, not a re-run of that exact scenario.

## Teardown

`sb cleanup <name>` after each trial (`subject-a`, `subject-b`, `subject-c` all closed;
`sb status` in the clone shows `0 alive` after the third). `sb doctor` in the clone
reported no collector ever ran (every spawn used `--no-board`), so there was no panel
process to kill. The clone directory itself is scratch under this session's scratchpad and
was not merged, pushed, or referenced by anything outside this probe; it is left in place
for now in case anyone wants to re-inspect the transcripts, but nothing in the live repo or
fleet depends on it.

## Reproducing

Subject task files and raw `/tmp` log files are not committed (they lived in the scratch
clone, torn down as agents but not deleted from disk). The commands to reproduce are
exactly as described above: clone `main`, `sb start --no-board` a subject with a
single-long-tool-call task, watch its `/tmp` log fill, fire `herdr agent prompt <name>
"..."` (or `herdr pane send-text <pane> "..."` + `herdr pane send-keys <pane> enter`) partway
through, and compare the log's own timestamps (ground truth) against the agent's
self-reported awareness time and `sb inspect`'s transcript.
