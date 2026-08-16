# Modal-vs-stalled: real captures and a verdict

Task `.scout/modal-capture.md`, follows on `notes/researcher-61-modal-scout.md`. All work
done in an isolated `git clone` of this repo (`board-awaiting-keypress` checked out) plus a
throwaway herdr workspace (`w1HK`, label `modal-scout`) of raw panes — not run through
`sb delegate`, because the modals in question occur *before* a normal switchboard-tracked
session exists (first-run onboarding) or require an unauthenticated/untrusted state that
`sb`'s own workspace never produces. Everything created (7 panes, 1 workspace, 2 scratch
dirs) was torn down; `herdr workspace list` after cleanup no longer lists `modal-scout`.
Raw captures are in `research/modal-captures/01`–`09` (verbatim `herdr pane read` +
`herdr agent get` + `herdr agent explain` output). This note is the analysis.

## Verdict up front

**A rule exists that separates every modal I captured from every negative control I
captured, and it is cheaper than reading pane text: `herdr agent explain`'s own `rule`
field.** But I could only capture one family of modal (first-run onboarding: theme picker,
login-method picker) — not the trust-folder prompt or the auto-mode dialog, both explicitly
asked for in the brief — so this is confirmed for that family only, not "all Claude Code
modals." See "What I could not reproduce, and why" below; this is a real gap, not a
formality.

## What I captured

**Positive (modal-parked), `research/modal-captures/01`–`03`:** a fresh `CLAUDE_CONFIG_DIR`
(no `~/.claude.json`, no auth) run with `herdr agent start <name> --kind claude --pane <id>`
so it's a normally-registered named agent, not a bare `herdr pane run`. Landed on the
first-run theme picker, then (after `enter`) the login-method picker — the *same* dialog
`learnings/stuck-agent-interrupt.md` describes reaching before, but this is the first time
its full pane text and `herdr agent explain` output are captured verbatim in-repo. On both
screens:
- `herdr agent get` → `"agent_status":"idle","interactive_ready":true` — indistinguishable
  from a healthy, ready agent by these fields alone.
- `herdr agent explain` → **`rule: none`**, `fallback_reason: default_known_agent_idle_fallback`
  — herdr's own classifier did not match a rule for this screen at all; it fell back to a
  generic "known agent, assume idle" default. This is the load-bearing fact: herdr isn't
  quietly recognizing the modal as idle, it's giving up and guessing idle.
- `Esc` did nothing on the login-method picker (confirms the prior note's finding, on a
  second, independently-reproduced instance of the same screen).

**Negative controls, `04`–`09`:**
- `04`–`06`, real tool-permission prompts (rm, file-create, run-script) in a trusted repo,
  `--permission-mode default`: `agent_status: blocked`. `herdr agent explain` **matches** a
  real rule — `generic_permission_prompt` (region=`after_last_horizontal_rule`,
  priority=840) on two of three, `legacy_no_prompt_blocker` on the third — each with the
  literal evidence text ("Do you want to proceed? ... Esc to cancel").
- `07`, an agent that just finished a turn and is sitting at an empty, ready prompt box
  (the closest herdr-visible proxy for honest STALLED — see caveat below):
  `agent_status: idle`, `interactive_ready: true` (same shape as the modal captures at the
  `agent get` level), but `herdr agent explain` **matches** `live_prompt_box`
  (region=`prompt_box_body`, priority=950), evidence being the model's suggested-next-input
  text sitting in the prompt box.
- `08`, actively working (mid tool-run): `agent_status: working`, rule matched:
  `osc_title_working`, evidence being the spinner glyph in the terminal title
  (`◐ Remove temporary test directory`).
- `09`, a plain shell pane with no agent at all: `agent_status: unknown` — a third,
  distinct bucket from both the modal case (`idle`, unmatched) and the working/blocked
  cases (matched rules).

## The rule, checked against all 9 captures

**Fires on:** `herdr_state == idle` AND `herdr agent explain`'s rule is the fallback
(`rule: none`, `fallback_reason: default_known_agent_idle_fallback`) rather than a matched
rule.

- Captures 01–03 (modal): fires. Correct.
- Captures 04–06 (blocked): `agent_status` is `blocked`, not `idle` — excluded before the
  rule field is even checked.
- Capture 07 (idle, turn just ended, proxy for honest STALLED): `idle`, but the rule
  **matched** (`live_prompt_box`) — does not fire. Correct.
- Capture 08 (working): `agent_status` is `working` — excluded.
- Capture 09 (no agent): `agent_status` is `unknown` — excluded.

So: on these 9 captures, `agent_status == idle && explain.rule == fallback` cleanly
separates "sitting on an unrecognized screen" from every negative control, at a per-agent
cost that's already paid by anything already calling `herdr agent explain` — it is not a
new pane-text heuristic switchboard would have to invent and maintain; it's herdr's own
existing manifest-driven classifier's confidence signal, repurposed.

## What this rule would likely miss

- **Any modal herdr's manifest already has a specific (if wrong) rule for.** A modal that
  happens to *look* like a permission prompt or a working spinner to herdr's regex-driven
  manifest would match a rule and this signal would say "not modal" — false negative,
  silently falls back to today's plain STALLED, which the brief accepts as the safe
  failure mode.
- **The trust-folder prompt and the auto-mode dialog specifically — untested.** These are
  the two modals the brief names by name and I could not reproduce either; see below. I do
  not know whether they also produce `rule: none` or whether herdr's manifest has (correct
  or incorrect) specific rules for them. Given herdr's manifest already has purpose-built
  rules for permission prompts and working states, it is plausible it also has one for the
  trust dialog specifically (it's an extremely common screen) — which would make this
  narrower than "all modals," possibly closer to "modals herdr's authors didn't anticipate."
- Any degraded case where `explain` itself can't be run (raises, times out) isn't covered
  by anything captured here.

## What I could not reproduce, and why (this matters for the miss-list above)

- **Trust-folder prompt:** Andrew's real `~/.claude/settings.json` has
  `"skipDangerousModePermissionPrompt": true` and `"skipAutoPermissionPrompt": true` set
  globally. I confirmed live that a brand-new, never-before-seen directory
  (`/private/tmp/modal-scout-untrusted-*`, `hasTrustDialogAccepted: false` in
  `~/.claude.json`'s per-project entry) produced **no trust dialog at all** — straight to
  the normal ready prompt. Reproducing the dialog would need either editing Andrew's real
  global settings (out of scope — that's his live config, not something in the isolated
  clone) or running under a from-scratch `CLAUDE_CONFIG_DIR` with real OAuth credentials,
  which requires copying his auth into a throwaway config; I did not do that (a shell
  command that tried to just *read* the relevant fields to check feasibility was itself
  blocked by the permission classifier, which I take as a clear signal not to pursue it).
- **Auto-mode dialog:** fires at `query_end` after a real, authenticated turn completes
  (confirmed by `notes/auto-mode-dialog-suppression.md`). A fresh `CLAUDE_CONFIG_DIR` gets
  me to the login-method picker (captured, `03`) but not past it without a real login —
  same credential wall as above.

Both are legitimately open. I'm reporting the gap rather than stretching the two captures I
do have into a claim about "modals" in general.

## Direct answer to the brief's four questions

1. **Does a rule exist that fires on every captured modal and none of the controls?** Yes —
   see "The rule" above, checked against all 9 captures.
2. **State it precisely / what it would miss:** done above. It's `agent_status == idle &&
   herdr agent explain reports the unmatched fallback rule` — cheap, reuses herdr's own
   classifier. It would likely miss the trust-folder and auto-mode dialogs specifically if
   herdr's manifest has purpose-built (possibly wrong) rules for those already; unproven
   either way.
3. N/A — a rule does exist for the captured family.
4. **Do `herdr agent get`'s own fields already separate the cases, without reading pane
   text at all?** **No.** `agent_status`/`interactive_ready` are identical
   (`idle`/`true`) between the modal captures and capture 07 (idle-at-prompt, the closest
   proxy to honest STALLED). The separation only shows up in `herdr agent explain`'s `rule`
   field, which is derived by reading pane text under the hood — so it's not free of pane
   reads, but it is free of switchboard having to write and maintain its own pane-text
   parser, since herdr's manifest already does that parsing and already exposes whether it
   matched anything.

## Unproven / left for whoever builds this next

- Whether `rule: none` / `default_known_agent_idle_fallback` is specific to modals, or
  whether other unrelated unfamiliar-but-not-modal screens also hit it (a foreign REPL, a
  crashed shell that still looks like a prompt, an unusual Claude Code version's screen).
  I did not test any such case.
- The trust-folder and auto-mode dialogs, per above — genuinely open.
- Cost of calling `herdr agent explain` (vs `read_pane`) per-tick at fleet scale; I did not
  measure its latency, only used it as a diagnostic. `researcher-61`'s cost analysis of
  `read_pane` (`notes/researcher-61-modal-scout.md` §2) likely applies similarly since
  `explain` also has to read the pane, but I did not confirm that assumption by timing it.
- Whether `herdr agent explain --json` gives a clean machine-parseable shape for this
  (`rule`/`fallback_reason` as top-level keys) — I only saw its `--help` listing `--json`
  as an option, I did not actually run it with `--json` live.

Captures: `research/modal-captures/01-theme-picker.txt` through `09-idle-shell.txt`.
