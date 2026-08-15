# Why `sb tell --interrupt` didn't free the two agents stuck on the auto-mode dialog

Task: `.switchboard/tasks/stuck-agent-interrupt.md`. Investigate-only, no source edits.
All live testing done in a throwaway `git clone` driven by that clone's own `./bin/sb`,
plus a few raw `herdr` calls against throwaway workspaces. Everything created was torn
down (see "Teardown" at the end).

## 1. What `sb tell --interrupt` actually does, mechanically

`Broker._interrupt` (`switchboard/broker.py:3977-4023`):

1. Refuses outright if the target is finished-and-unreachable (`_finished_and_unreachable`,
   `broker.py:4089`) — not the case here, the pane was alive.
2. `self.h.send_keys(name, "esc")` (`broker.py:4011`) → `Herdr.send_keys`
   (`switchboard/herdr.py:825-833`) → `herdr agent send-keys <name> esc`, a raw keystroke
   sent to the pane. **Failures here are swallowed**: wrapped in `try/except HerdrError`,
   logged as `interrupt_stop_failed`, and execution continues regardless
   (`broker.py:4009-4014`, comment: "Always lands now — deferring an interrupt would
   defeat it entirely").
3. `time.sleep(INTERRUPT_SETTLE)` — a fixed short pause, config key
   `timeouts.interrupt_settle` (`broker.py:112-114`).
4. The interrupt's own text is put on the wire via `Broker._ring(name, body,
   mode=INTERRUPT)` (`broker.py:4020`, `_ring` at `broker.py:4304`). For every mode
   including `interrupt`, `_ring` calls **`self.h.prompt(who, text)`**
   (`broker.py:4388`) — `Herdr.prompt` (`herdr.py:600-626`), a **single, unconfirmed**
   call: type the text into the pane's prompt box, press Enter, return. No retry, no
   proof of arrival.

That last point is the crux. Contrast with how a **spawn** delivers its first task:
`Broker._delegate` calls `Herdr.deliver()` (`herdr.py:628-713`), which retries up to
`SPAWN_ATTEMPTS` times and only succeeds once `proof()` shows the text actually reached
the agent's own transcript (or, as a fallback, herdr reports a fresh `working` turn).
`deliver`'s own docstring explains exactly why: on a fresh checkout, "a Claude Code still
showing its workspace trust dialog eats the prompt and changes state anyway" — three of
four cold-fanout spawns were confirmed to fail exactly this way before `deliver()` was
hardened against it (`herdr.py:648-655`, `broker.py:3236-3238`).

**`_interrupt` never goes through `deliver()`.** It goes through `_ring` →
`h.prompt()`, the same unconfirmed one-shot call that `deliver()` was written to stop
trusting. There is no proof step and no retry for an interrupt's own message.

## 2. Why it didn't dismiss the dialog, when Andrew's own Escape did — proven live

Live test (raw `herdr` calls against a throwaway workspace/pane, Claude Code sitting on
a real first-run modal — the login-method picker, reached by starting `claude
--permission-mode auto` in a pane with an isolated `CLAUDE_CONFIG_DIR`):

- `herdr agent get <name>` reported `"interactive_ready": true, "agent_status": "idle"`
  **while sitting on the raw onboarding screen**, before any real session existed. So
  herdr's name→pane binding is intact and targetable through this whole window; the
  "not an active named agent" failure mode documented elsewhere in `herdr.py` does not
  explain this case.
- `herdr agent send-keys <name> esc` returned `{"type":"ok"}`. The keystroke reached the
  pane. The dialog on screen did not change — because *that particular* dialog (the
  login-method `Select`) has no Escape/cancel binding; some early screens simply don't
  listen for it.
- `herdr agent prompt <name> "hello there this is a test message"` then reproduced
  `deliver()`'s documented failure mode exactly: the pane advanced to "Opening browser
  to sign in…" (the Enter answered/selected the dialog's highlighted default) and the
  prompt text itself never appeared anywhere — it was silently discarded. herdr's own
  `agent_status`/`state_change_seq` did not even move to reflect it.

So the mechanism `_interrupt` relies on is real (`send_keys` does deliver a literal
keystroke to the pane, mechanically identical to Andrew typing Escape himself), but
**whether Escape does anything at all is entirely up to the specific screen currently
showing**, and the follow-up message delivery has zero protection against being eaten by
whatever screen is showing after it.

I could not get all the way to reproducing the exact "Set up auto mode for your
environment?" dialog live (see §5 — it's gated behind a real login, and I was not willing
to copy Andrew's OAuth credentials into a throwaway config to get past that wall). But I
decompiled the relevant logic out of the installed `claude` binary
(`/Users/andrew/.local/bin/claude`, v2.1.232) to check whether *that specific* dialog
behaves the way `_interrupt` would need it to:

```
case "accept": ...
case "later":  N("tengu_auto_mode_env_onboarding_later",{}), rn(TSw,X8i), jNh(); break
case "dismiss": ...
```
and the modal's `onCancel` handler is wired to `()=>Ket("later")` — so Escape on *this*
dialog does answer it, with "later". That part should work. What I could confirm live,
against a same-shaped Claude Code first-run screen, is that even when Escape does its
job, the **very next** unconfirmed `h.prompt()` call is a coin flip: if the "later"
answer landed the pane on the real prompt, the interrupt's message arrives; if it landed
on any other screen (another dialog, a spinner, a re-prompt), the message is silently
eaten and `_interrupt` reports success anyway. Given §5 below, the two stuck agents were
almost certainly single-dialog cases (this is a one-time-per-week prompt, not a chain),
so the more likely reading is: the `esc` **did** land and **did** answer "later" —
but that is not the end of the story either. Not proven live, but consistent with
everything above: **the timestamp evidence in §5 shows the dialog *was* answered around
the time Andrew intervened**, which is also consistent with `_interrupt`'s blind `esc`
having landed and only the interrupt's own follow-up text (not a second Escape) having
been swallowed by whatever came right after "later" was chosen (this Claude Code version
appears to show a related second first-run screen right after, per `wJr`/"auto default
notice" logic found in the same bundle) — i.e., **one blind keystroke wasn't enough to
walk a stuck pane all the way back to a state that would accept a typed prompt**, exactly
the class of failure `deliver()` exists to catch and `_interrupt` does not.

**Bottom line on Q2:** `_interrupt` sends Escape best-effort (errors swallowed) and then
delivers its own message with the same *unconfirmed, un-retried* primitive that spawn's
`deliver()` was specifically hardened against. Andrew's manual Escape worked because he
could see the actual screen and confirm he'd reached a real prompt before doing anything
else; `sb tell --interrupt` cannot see the pane and has no confirmation step for its own
delivery.

## 3. Could switchboard send a real Escape keypress to a pane? — yes, it already does

`herdr agent send-keys <name> esc` is exactly a raw Escape keystroke into the pane's
terminal, and I confirmed live (above) that it lands regardless of whether a real Claude
session has started. `_interrupt` already uses this. **The mechanism exists and works.**
What's missing is not the keystroke — it's (a) knowing when to send it, and (b)
confirming its own follow-up message isn't then eaten by whatever screen comes next.

**The risk of firing Escape at a normally-working agent, tested live:** I ran
`sb tell --interrupt` against a healthy, running agent (real code path, real store, real
Claude session). Event log:

```
unblocked  {"reason": "told_by_human"}
interrupt  {"stopped": true, "text": "IMPORTANT: this is an interrupt ..."}
done       {"summary": "interrupt test received"}
```

It worked cleanly — the agent's current turn was cancelled and it picked up the new
instruction, exactly as DESIGN-TRUTH.md describes ("interrupt... cancelling what the
agent was doing. Used when we need to change course, or the agent is doing something
wrong" — DESIGN-TRUTH.md:251-252). But that is exactly the danger of doing this
*automatically*: Escape cancels whatever the model's current turn is doing, mid-flight —
including, plausibly, a Bash tool call already running. Nothing in what I read or tested
here shows a running shell command being cleanly rolled back; the model's turn is
cancelled, not necessarily whatever process it kicked off. Firing Escape at an agent that
is merely *slow* (a long build, a long test run) rather than genuinely stuck is not a
free action — it is the documented "change course" verb, applied blind.

## 4. Is a prompt-level rule the right answer?

Andrew's suggestion — "when an agent is stuck, try an interrupt to clear any dialog" —
cannot live in the stuck agent's own prompt: a pane sitting on a pre-session dialog has
no model reading anything yet (confirmed live in §2 — `agent prompt` types into the void
and the text vanishes). Whoever acts has to be someone *else*, watching from outside:

- **The parent**, on seeing a child go STALLED: plausible, but a parent only looks when
  it happens to check (`sb status`), and the task says this went undetected for hours —
  four queued messages, no parent action. A prompt rule telling parents "if a child is
  STALLED, try `sb tell --interrupt` once" is cheap to add and harmless if it also fixes
  §1's follow-up-delivery gap, but it only fires when someone happens to be looking.
- **The human**, via `sb block`/dashboard: not applicable — nothing was blocked, nothing
  reached a human at all until Andrew noticed independently.
- **Switchboard itself**, automatically, on detecting a stall (something like the
  collector or a stall-sweep already referenced in `design/fix-options.md` around
  "genuinely stuck" detection): the only option that doesn't depend on somebody
  happening to look. This is the one Andrew's phrasing ("something should try") points
  at, and it's the only one that would have actually closed the hours-long gap in the
  real incident.

**Recommendation:** don't put this in a prompt at all. If recovery is wanted, it belongs
in the stall-detection path switchboard already has (whatever currently marks an agent
STALLED), as a bounded, logged, one-shot `esc` — and it should reuse `deliver()`'s
proof-based confirmation for the follow-up message instead of `_ring`'s bare
`h.prompt()`, or it will just repeat this exact bug. Scope it tightly (only agents that
have *never* taken a first turn — `awaiting_task`/no transcript at all — not any slow
agent) given §3's risk on a healthy agent. This is a recovery mechanism, though — see §5
for why prevention is very likely the better fix and should be tried first.

## 5. Should this be prevented rather than recovered from? — yes, and the mechanism is now understood precisely

Decompiled from the installed `claude` binary (`/Users/andrew/.local/bin/claude`,
v2.1.232). The dialog is gated by one function (renamed variables kept as found):

```js
function yrc(){
  if(!xai())return!1;                                   // not applicable outside interactive TUI
  if((j2e()?.environment?.length??0)>0)return!1;         // already has auto-mode env rules configured
  let e=or();
  if(e.numStartups<_Sw)return!1;                         // _Sw = 5: never shows before the 5th startup
  if(bSw())return!1;                                     // suppressed if the (different) "auto mode is
                                                          // now default" notice already fired
  let t=e.autoModeEnvSetup;
  if(t?.dismissed)return!1;                               // "Don't show again" was chosen — permanent
  if(t?.dismissedAt && Date.now()-t.dismissedAt<ySw)      // ySw = 604800000 = 7 days
    return!1;                                             // answered "later" less than 7 days ago
  return!0;                                                // otherwise: show it
}
```

`e = or()` reads the account's global state file, `~/.claude.json` (confirmed by reading
it: it holds top-level keys `numStartups`, `autoModeEnvSetup`, `hasCompletedOnboarding`,
etc.). This is **not per-project and not per-worktree** — it is one file per OS user,
shared by every Claude Code session on the machine, live fleet and any clone alike.

Live corroboration, read-only, against Andrew's real `~/.claude.json`:
- `numStartups`: 1587 — nowhere near the "never before startup 5" floor; this account
  passed that threshold long ago, so the dialog is armed at all times subject only to
  the 7-day cooldown.
- `autoModeEnvSetup.dismissedAt`: **2026-08-14 12:51:45** — i.e. *today*, matching this
  task's own timeline. This is exactly what choosing "later" (or Andrew's manual Escape,
  which is wired to the same "later" branch — see §2) writes.

**So this is not a fresh-machine, one-off problem.** It is a dialog that re-arms itself
every 7 days (unless someone explicitly picks "Don't show again," which is the only
branch that sets `dismissed: true` and disarms it for good) — and because
`~/.claude.json` and `numStartups` are shared globally, **every Claude Code process on
the machine started after the 7-day window re-elapses is independently eligible to hit
it**, including several launched at once by a fan-out. That is exactly the shape of the
incident: two agents spawned around the same time both landing on it simultaneously,
each blocking before anyone could answer either.

I could not fire this exact dialog live end-to-end (it needs a real login, which needs
either a throwaway authenticated account or borrowing Andrew's OAuth session into a
scratch config — I judged copying his credentials out of `~/.claude.json`/keychain into
a hand-built file, even locally and even for a test, to be handling auth material more
casually than this task warrants, so I stopped short of it and did not do it). What I did
confirm live and by direct decompilation is the exact gate above, and that it matches
the account's real, current state precisely.

**Recommended fix — prevention, not recovery, and it is close to the one-line setting
this task asked for if the answer turned out to be that simple:**

Pre-seed `~/.claude.json`'s top-level `autoModeEnvSetup` field to `{"dismissed": true}`
— literally the value the "Don't show again" button itself writes (see `wSw` in the
decompiled snippet: `{...state, autoModeEnvSetup: {...state.autoModeEnvSetup,
dismissed: true}}`) — once, e.g. at `sb doctor`/`sb init` time, before any agent is ever
spawned. That is a one-field write to one file (`~/.claude.json`, top-level key
`autoModeEnvSetup`), not a source change, and it is exactly what a human clicking
"Don't show again" once would produce. I did not make this write myself: it touches
Andrew's real, shared, global `~/.claude.json`, used by the live fleet and by every
future Claude Code session on the machine — squarely the kind of shared-state,
hard-to-reverse-if-wrong change this task told me not to make in this pass, and it wants
his sign-off (it also permanently opts him out of ever seeing that dialog again,
anywhere, which is a real product-behavior tradeoff someone should choose knowingly
rather than have an agent decide).

I found no supported, documented settings.json-level knob for this specific dialog.
There IS a settings key, `skipAutoPermissionPrompt` (already `true` in Andrew's own
`~/.claude/settings.json`), but decompiling its use (`$Nl`/`shouldShowAutoModeEntryWarning`)
shows it gates a *different* first-run screen — the "Auto mode is now Claude Code's
default permission mode" notice — not `autoModeEnvSetup`'s "Set up auto mode for your
environment?" wizard. The two are easy to conflate; they are separate dialogs with
separate state and separate gating logic in the binary.

## What's proven vs. not

**Proven live:**
- `herdr agent send-keys <name> esc` delivers a real keystroke to a pane sitting on a
  Claude Code first-run screen, before any session/hooks exist, with herdr reporting the
  name as bound and ready throughout.
- `herdr agent prompt` (what `_ring`/`_interrupt`'s follow-up message uses) silently
  discards its text when the pane is on such a screen — the Enter just answers whatever
  is showing, with no error and no visible trace of the lost text.
- `sb tell --interrupt`, run through the real `Broker._interrupt` code path in an
  isolated clone against a healthy running agent, cleanly cancels its turn and delivers
  the new instruction (event log: `interrupt {"stopped": true}` → agent responds → `sb
  done`).
- The exact gating logic and state (`autoModeEnvSetup`, `numStartups`, the 5-startup
  floor, the 7-day cooldown, the "dismissed forever" vs. "later" branches) by
  decompiling the installed `claude` binary, and its current values in Andrew's real
  `~/.claude.json` line up with this task's own timeline.

**Not proven — honestly unproven, not guessed:**
- I did not reproduce the literal "Set up auto mode for your environment?" dialog live
  end-to-end, because doing so needs a real login and I chose not to smuggle Andrew's
  credentials into a throwaway config to get one.
- I did not verify live whether Escape on *that* dialog, followed by `_interrupt`'s
  immediate unconfirmed prompt, does or does not land — only that the equivalent failure
  mode reproduces on a same-shaped first-run screen, and that the decompiled source wires
  that dialog's Escape to "later".
- I did not test writing `autoModeEnvSetup.dismissed = true` — recommended, not applied,
  and it should be a decision Andrew makes deliberately since it's global and permanent.

## Teardown

Everything created during this investigation was closed/removed:
- `sb cleanup --force interrupt-probe` in the clone (closed the `sb`-tracked test
  orchestrator).
- `herdr workspace close w1CV` / `w1CY` (the two throwaway herdr workspaces used for raw
  keystroke/prompt tests).
- `ps aux` confirmed no `claude` process referencing the scratch clone path or either
  test agent name remained.
- The scratch `git clone` and the throwaway `CLAUDE_CONFIG_DIR`/`HOME` directories used
  for isolation were deleted.
- Andrew's real `~/.claude.json` was only ever read, never written, during this pass.
