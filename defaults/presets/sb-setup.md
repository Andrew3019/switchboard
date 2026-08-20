<!--
Notes for whoever edits this file. HTML comments are stripped on the way out, so this is
free; everything outside it is read whole by whoever ran `sb presets sb-setup`.

READ AS PROSE, NEVER FLATTENED — like `adversarial` and `design-gate`, and unlike
`evidence`/`verify`. Nothing binds this file to a role or to `all`; it is reached by a
person asking for it, or by a dispatcher offering it from the operator-skills menu and the
human saying yes. So its layout IS load-bearing: the tables below are read as tables, and
an editor who reflows them into sentences has removed the thing that makes the walkthrough
executable in one pass.

WHY A PRESET AND NOT A CLAUDE CODE SKILL. A `.claude/` skill cannot travel to the repos
that merely USE switchboard — sb installs nothing into a repo, and `.claude/` is commonly
gitignored. A shipped preset is nameable in every repo with zero install, which is the
whole point of a setup procedure: it has to exist before the repo has been set up.

WHY THE KEY LIST IS SHORT AND MUST STAY SHORT. `defaults/settings.toml` is ~670 lines and
almost all of it is measurement-backed tuning with a paragraph justifying each number, or
`[herdr]`, whose own comment says these are facts about the binary rather than preferences.
Exactly three rows below are real per-repo human choices. Every key added here is a key a
setup walkthrough invites a stranger to change on a guess, so the bar for a fourth row is
"a person could know the right answer without measuring anything".

WHY TIER 2 STOPS AT PRESETS AND ROLES. Both are discovered by filesystem glob with no
registration step, so generating one is a file write and nothing else. A plugin is Python
that ships and runs on other people's machines — that is a change that lands, with a plan
and a PR, and not something a walkthrough authors on the spot.

THE GUARDRAILS ARE FIRST FOR A REASON. `.switchboard/` is symlinked worktree→main, so the
single most likely mistake — running this in a worktree — silently rewrites the config of
every agent on the machine. It is stated before anything the agent could act on, because a
guardrail placed after the first write instruction is a guardrail that arrives late.
-->

# sb-setup

Set up this repo's switchboard config, with the human who asked in the loop. You read the
current state, offer only what is actually missing, show every write before you make it,
and make it where it belongs. Nothing here is autonomous: each step ends with the person
saying yes.

Re-running this is normal and must be safe. Everything below is written so that a second
run over a configured repo offers nothing and changes nothing.

## Before anything: three rules that do not bend

**Only write from the main checkout.** `.switchboard/` in a worktree is a SYMLINK to the
main checkout's directory, so a write from a worktree is not local to you — it changes the
config every agent on this machine reads. Check before you write:

    git rev-parse --git-dir --git-common-dir     # two different paths = you are in a worktree
    ls -ld .switchboard                          # a symlink names the main checkout it points at

If they differ, stop and say so, naming the main checkout path the symlink points at, and
let the person decide: run this there, or tell you to go ahead knowing the change is
machine-wide. Do not make that call yourself.

**Never write `.switchboard-shared/`.** It is tracked, so anything you put there is a
change that lands, and a change that lands takes the normal branch-and-PR route with a
human reviewing it. Per-machine config is `.switchboard/` and only `.switchboard/`. If what
the person wants really belongs in the shared, tracked config, say that and stop — this
walkthrough is not the way to do it.

**Read, merge, write — never blind-write a TOML.** These files are small and load-bearing
and are commonly hand-edited. `.switchboard/plugins.toml` is the sharp one: it holds both
`enabled` and a repo's `[roles]` plugin bindings, so writing it fresh from what you know
about one key deletes bindings nobody mentioned. Read the current file, merge your one
change into what is there, write it back. If it does not exist yet, creating it with only
your change is correct — that is a merge with an empty file.

## First, read the current state

Before offering anything, read all of these. Any of them may be absent; absent means
"shipped defaults apply", not an error.

- `.switchboard/settings.toml` — which of the Tier 1 keys are already set.
- `.switchboard/plugins.toml` — is `"todo"` already in `enabled`?
- `.switchboard/presets.toml` — is `"@todo"` already in `all` or under `[roles]`?
- `.switchboard/roles/*.md` and `.switchboard/presets/*.md` — what has already been
  generated here.

Then offer the person only the deltas. A key already set is not a question; skipping it
silently is right, and re-asking it is the thing that makes a second run feel broken.
`sb plugin list` renders the current enabled-and-bound state if you want to show it rather
than describe it.

## Tier 1 — the config values worth asking about

Three rows, and only three. Everything else in `settings.toml` is tuning with measurements
behind it; do not offer it, and do not volunteer it if asked to "go through the settings".

| key | shipped default | ask only when | what you write |
|---|---|---|---|
| `editor.command` | `"cursor"` | their editor is not Cursor | `[editor]` / `command = "code"` |
| `vocabulary.base_branch` | `"origin/main"` | the repo's default branch is not `main` | `[vocabulary]` / `base_branch = "origin/master"` |
| `sweep.docs_dirs`, `sweep.docs_never` | `["notes", "design", "learnings", "research"]`, `['DESIGN-TRUTH.md']` | this repo's docs live under other directory names | `[sweep]` / `docs_dirs = ["docs"]` |

`editor.command` is a CLI that must accept a folder and VS Code-style `-r -g <file>` flags;
it is what the board's `oo` action shells out to. `vocabulary.base_branch` is what a new
worktree forks from when `--base` is not given — check what the repo's default branch
actually is rather than asking the person to remember. `docs_dirs` decides which stranded
commits the sweep treats as docs-only and may therefore clean up, so a repo whose notes
live in `docs/` and is not told so has its notes counted as real work; `docs_never` is the
list of files that are never docs however they are spelled, and a repo with its own
single trusted document should say so there.

These arrays JOIN across layers rather than replacing, so name only what you are ADDING —
`docs_dirs = ["docs"]` gives this repo all five directories, not one. `"!reset"` as the
first element replaces the shipped list instead, and is what you write when the shipped
names are actively wrong here rather than merely incomplete.

TOML tables merge key by key, so writing just these keys leaves the rest of
`[editor]`/`[vocabulary]`/`[sweep]` alone. Show the person the exact lines, get a yes, then
read-modify-write `.switchboard/settings.toml`.

## Tier 1, continued — the `todo` plugin

`todo` ships, is not enabled, and is the only shipped plugin in that state. Offer it, and
say what it costs: every enabled plugin's bound fragment is carried by every spawn it is
bound to, forever. If they say yes, it is TWO decisions and two files, and doing only the
first is the common mistake — enabled means the human can run `sb plugin todo`; bound means
agents are told it exists.

`.switchboard/plugins.toml` — enable it:

    enabled = ["todo"]

`.switchboard/presets.toml` — bind it, either to everyone:

    all = ["@todo"]

or to one role, which is the cheaper answer when only some agents need it:

    [roles]
    worker = ["@todo"]

Both join onto the shipped lists, so again: name only the new thing. **The `@` sigil is
required.** A bare `"todo"` in `presets.toml` names a preset FILE, not a plugin fragment;
it is an error, not a silent no-op, and it is the single most likely typo in this step.

## Tier 2 — generate a role and preset for what this repo actually is

Sniff the repo type by file existence, most specific first. Stop at the first match: a
React Native repo also has a `package.json`, and an iOS repo checked after "plain Node"
never gets there.

| signal | type | generate |
|---|---|---|
| `react-native` dep in `package.json`, or `ios/*.xcodeproj` alongside `android/` | React Native | `mobile-qa` |
| `*.xcodeproj`, `*.xcworkspace` or `Package.swift`, with no RN markers | iOS / Swift | `ios-qa` |
| `build.gradle` or `build.gradle.kts`, at root or `app/` | Android | `android-qa` |
| `package.json`, no mobile markers | Node / JS / TS | `web-qa` |
| `pyproject.toml`, `setup.py` or `requirements.txt` | Python | `py-qa` |
| `go.mod` | Go | `go-qa` |
| `Cargo.toml` | Rust | `rust-qa` |
| `Gemfile` | Ruby | `ruby-qa` |

Nothing in sb does this for you and nothing will; it is a handful of existence checks.
Where the sniff is ambiguous — a monorepo, two of these side by side — say what you found
and ask, rather than picking the first row and calling it detected.

A generation is THREE files, and the third is the one people forget:

**1. `.switchboard/roles/<name>.md`** — TOML frontmatter fenced by `+++` (not the `---` YAML
fences Claude Code skills use; these are different conventions and crossing them breaks the
file), then the prose that becomes the role's prompt:

    +++
    model = "careful"
    delegate = false
    +++

    You are an iOS QA agent for this repo. Build and run the app in the simulator, verify
    that UI changes actually render, and check the adjacent screens for regressions before
    reporting good to go.

`model` must be a tier that already exists — the shipped ones are `cheap`, `default`,
`standard`, `careful`, `strong`, `prose`, plus anything this repo's own `models.toml` adds.
Do not invent a tier name; `sb models` prints what actually resolves here. `delegate` is
whether this role may spawn other agents, and defaults to false. There is no `prompt`
field: the body after the closing `+++` is the prompt.

**2. `.switchboard/presets/<name>.md`** — plain markdown, no frontmatter. The repo's actual
conventions for that kind of work, in the concrete: the real test command, the real
simulator or target, what evidence counts here.

**3. The binding line** in `.switchboard/presets.toml`:

    [roles]
    ios-qa = ["ios-qa"]

Left side is the role, right side is the presets appended to `all` for it. Without this
line the preset is nameable — `sb presets ios-qa` prints it — and never reaches an agent.
Shipping is not applying.

Nothing else is needed to make either file discoverable: both are found by glob, so
`--role ios-qa` works the moment the file is saved.

**Draft, show, confirm, then write.** Put the whole role body and the whole preset in front
of the person before any file exists. You are guessing at their conventions and they are
not — the draft is what makes that guess correctable, and a written file is a thing they
have to review rather than a thing they chose.

Do not author a plugin. Tier 2 is presets and roles: files that are read. A plugin is
Python that runs, and that goes through a plan and a PR like any other code.

## Re-runs: offer deltas, diff rather than clobber

The reads at the top are what make a second run cheap. Carry them through to the end:

- A settings key already present is skipped, not re-asked.
- `todo` already enabled and already bound is one line of "already done", not two offers.
- **A generated file that already exists is never overwritten.** Someone has probably
  hand-edited it since — that was the point of generating it. Show the difference between
  what exists and what you would generate, and let the person choose: keep, replace, or
  merge by hand. If nothing differs, say so and move on.

When you have nothing left to offer, say exactly that. "Already set up, nothing to change"
is a complete and correct result for this walkthrough, and is what most re-runs should
produce.
