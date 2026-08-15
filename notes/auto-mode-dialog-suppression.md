# Issue #38(a): suppressing the auto-mode dialog without touching the global config

Closes the "agents wedge on Claude Code's first-run auto-mode dialog" half of #38 the way
triage recommended (`notes/issue-triage-answers-2026-08-15.md`, branch `issue-triage`), not
the way the issue proposes. `~/.claude.json` is untouched.

## The change

`.claude/settings.json` (newly tracked — `.gitignore` now un-ignores that one file):

```json
{ "skillOverrides": { "auto-mode-setup": "off" } }
```

Repo-scoped, in version control, reversible by deleting the file. It has to be *committed*:
every worktree and clone is its own project root, so an uncommitted file reaches none of them.

## Why it works (claude v2.1.233, decompiled)

The dialog's gate bottoms out in:

```js
function xci(){ return wDa() && Wo().skillOverrides?.["auto-mode-setup"] !== "off" }
function eic(){ if(!xci()) return false; /* env configured, numStartups<5, dismissed, 7d cooldown */ }
```

`Wo()` is the **merged** settings object, so a project `.claude/settings.json` reaches it.
`xci()` is the first test in `eic()`, checked before any `~/.claude.json` state.

Two constants for the record: startup floor `$kw = 5`, cooldown `Bkw = 604800000` (7 days).

**Timing correction to #38.** The dialog is not raised at startup. `mUh(state)` is evaluated
at `query_end` — the modal appears when the agent's *first turn finishes*, not on a cold pane.
Reproduced that way below.

## Proved live

Isolated instance: `git clone` of this repo into a scratch dir, driven with
`CLAUDE_CONFIG_DIR` pointed at a throwaway config (`autoModeEnvSetup` removed,
`numStartups` seeded past the floor, `skipAutoPermissionPrompt: true`), started with
`claude --permission-mode auto`. Nothing in `~/.claude.json` or `~/.claude/settings.json`
was read-modify-written. Both runs used the same throwaway config and the same prompt; the
only difference was the presence of `.claude/settings.json` in the clone.

| | dialog after first turn | `/auto-mode-setup` in the slash menu |
|---|---|---|
| without the override | **appears** — "Set up auto mode for your environment?" | listed |
| with the override | **does not appear** (two turns) | "No commands match" |

The negative run's pane was killed without answering the dialog, so the throwaway config
still had no `autoModeEnvSetup` for the positive run — the two runs differ in one variable.

## Blast radius — one effect beyond the dialog

`skillOverrides["auto-mode-setup"] = "off"` also disables the `/auto-mode-setup` slash
command, in this repo only. That is not incidental: `auto-mode-setup` sits in the binary's
`sdb` set, so `IVe()` maps the same override onto the command, and the dialog's "Set it up"
branch does nothing but submit `/auto-mode-setup`. Confirmed live (table above).

Nothing else. `xci()` has exactly three call sites (its definition, `eic()`, and the dialog's
accept handler, which re-checks it and closes quietly). `skillOverrides` is keyed by skill
name, so no other skill is touched, and nothing in auto mode's *permission* behaviour reads
this key.

Outside a switchboard checkout, `/auto-mode-setup` and its dialog are unaffected.

## Unproven

- Whether the dialog can also appear on a pane that has never taken a turn. #38 reports two
  agents wedged before any session existed; the gate found here fires at `query_end`, and no
  startup-time path to the same modal was found.
- The server-side flag (`tengu_auto_mode_config.envOnboarding`) was `true` for this account
  throughout. If Anthropic turns it off, both runs would show no dialog for that reason —
  the negative run showing the dialog is what rules that out for the runs above, not for the
  future.
