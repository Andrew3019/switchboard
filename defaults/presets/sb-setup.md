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

THIS FILE NAMES NO KEYS, AND MUST NOT START — except as an illustration of layering
semantics, where naming one is unavoidable. The offer-set is DISCOVERED at run time from
`# setup:` tags in switchboard's own shipped `defaults/*.toml`, and the plugin toggles are computed live as
available-minus-enabled. That is deliberate: a key's prompt text lives once, in the tag
next to the value it describes, instead of twice — here and there — drifting apart. If you
find yourself adding a row naming a specific key, you are re-introducing the hardcoded
table this rewrite deleted; add a `# setup:` tag at the key instead.

WHY THE TAGGED SET IS SMALL AND MUST STAY SMALL. `defaults/settings.toml` is ~670 lines and
almost all of it is measurement-backed tuning with a paragraph justifying each number, or
`[herdr]`, whose own comment says these are facts about the binary rather than preferences.
A tag invites a stranger to change that key on a guess, so the bar for tagging one is "a
person could know the right answer without measuring anything". Absence of a tag is the
safe default and there is no anti-tag; the tag IS the allowlist.

WHY TIER 3 STOPS AT PRESETS AND ROLES. Both are discovered by filesystem glob with no
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

There is one exception to "creating it fresh is fine", and it is a plugin binding. Plugin
bindings (`all` / `[roles]`) once lived in `.switchboard/plugins.toml`; they now live in
`.switchboard/presets.toml`, and switchboard reads only ONE of the two — the moment
`presets.toml` exists, `plugins.toml`'s `all`/`[roles]` are never consulted again. So if
`.switchboard/plugins.toml` still holds `all` or `[roles]` bindings and `presets.toml` does
not exist yet, do NOT create `presets.toml` with only your one line: MOVE those existing
bindings into it in the same write, or the repo silently loses them. This bites exactly the
first-time-setup repo this walkthrough is for.

## Tier 1 — discover what this repo can be asked about

Nothing here is a fixed list. The set of questions is computed, every run, from two
sources: `# setup:` tags in switchboard's own shipped config, and the plugins this repo can
see but has not turned on. Do the discovery first, in full, before you say a word to the
person — the whole point is one batched offer at the end rather than a drip of questions.

**Find the tags.** The tags live in switchboard's OWN installed defaults directory —
wherever `sb` itself is installed — not in the repo you are setting up. `sb setup` runs in
any repo that merely USES switchboard, and such a repo has no `defaults/` of its own, so
resolve the directory first rather than assuming the current working directory:

    DEFAULTS="${SWITCHBOARD_DEFAULTS:-$(dirname "$(dirname "$(readlink -f "$(command -v sb)")")")/defaults}"
    grep -n '^[[:space:]]*#[[:space:]]*setup:' "$DEFAULTS"/*.toml

That is the shipped layer only. The target repo's own `.switchboard/*.toml` is this
walkthrough's OUTPUT — you read it separately, as the override layer, to see which keys are
already answered — and it is never a source of tags.

**Confirm you actually found them, and fail loudly if not.** Before you go any further,
check that the resolved `$DEFAULTS` directory exists and contains `settings.toml` — or
equivalently that the grep matched at least the shipped tags. If it did not, switchboard's
defaults could not be located: STOP and say so plainly to the person, naming the path you
tried. Do NOT conclude there is nothing to offer, and do NOT fall through to Tier 3.
"Discovery found nothing open" is a valid state ONLY after the defaults were successfully
located and every tagged key turned out to be already answered.

Each hit is one askable key. Read the file around it, don't just take the line.

**Parse each tag.** A tag is one comment line whose payload is a TOML inline table:

    # setup: { type = "string", hint = "...", when = "..." }

The fields:

| field | required | meaning |
|---|---|---|
| `type` | yes | `"string"`, `"list"`, `"bool"` or `"enum"` — the shape of the answer |
| `hint` | yes | the plain-language prompt you put to the human, written at the key |
| `choices` | only when `type = "enum"` | the allowed values, as an array |
| `when` | no | a prose condition for WHETHER to ask — a fact about the repo for you to check |
| `key` | no | an explicit dotted target, overriding the positional rule below |

**Resolve each tag's target.** The tag sits immediately above the key it describes, and is
the last line of any prose comment block above that key. So the target is the next
non-comment, non-blank line: `<current [section]>.<key>`. An explicit `key` field overrides
that. A tag whose target you cannot resolve is a bug in the shipped file — report it, do
not guess.

The `key = value` line under the tag is also the shipped default, so that one read gives
you both the question and the current answer-if-nobody-says-otherwise. Nothing else to look
up.

**Then read what this repo has already answered.** For each tagged key, read the repo's
matching `.switchboard/<same file name>` — `.switchboard/settings.toml` for a tag found in
`defaults/settings.toml`, and so on. Absent means "shipped defaults apply", not an error.
If the dotted key appears there, it is already answered: skip it silently. Re-asking an
answered key is the thing that makes a second run feel broken.

**Compare deltas the way sb merges layers, not by string equality.** The repo's file is an
override layer, not a replacement, and three rules decide what "already answered" means:

- **Tables merge key by key.** A repo that sets one key under `[sweep]` has not touched the
  rest of `[sweep]`. Writing your one key back leaves its neighbours alone.
- **Arrays JOIN across layers.** A repo whose `docs_dirs` reads `["docs"]` has all of the
  shipped names PLUS `docs`; it has not dropped them. That it does not re-list the shipped
  names is not a reason to re-offer the key — it is what a correctly-answered list key
  looks like.
- **`"!reset"` as the first element replaces instead of joining.** A repo that means the
  shipped list is actively wrong here, rather than merely incomplete, says so that way.
  That is still an answer, so still a skip.

**A `when` is yours to check, not to assume.** It names a fact about the repo — the actual
default branch, what the editor is — and expects you to go and look. If the fact says don't
ask, don't ask, and say nothing about it. If it says ask, remember what you found: the
person sees it as your reason for raising the question at all.

## Tier 2 — plugins this repo could turn on

Toggles carry no tag; they are computed live, so a plugin that ships off tomorrow shows up
here with no edit to this file. The set to offer is *available minus enabled*:

    sb plugin list --json

Every entry with `"enabled": false` is a candidate, and its `"help"` is the plugin's own
one-line description — use that when you explain it, rather than anything you remember
about a particular plugin. Offer each one and say what it costs: every enabled plugin's
bound fragment is carried by every spawn it is bound to, forever.

If they say yes, it is TWO decisions and two files, and doing only the first is the common
mistake — enabled means the human can run `sb plugin <name>`; bound means agents are told
it exists.

`.switchboard/plugins.toml` — enable it:

    enabled = ["<name>"]

`.switchboard/presets.toml` — bind it, either to everyone:

    all = ["@<name>"]

or to one role, which is the cheaper answer when only some agents need it:

    [roles]
    worker = ["@<name>"]

Both join onto the shipped lists, so again: name only the new thing. **The `@` sigil is
required.** A bare `"<name>"` in `presets.toml` names a preset FILE, not a plugin fragment;
it is an error, not a silent no-op, and it is the single most likely typo in this step.

A plugin already enabled AND already bound is one line of "already done", not two offers.
Enabled but not bound is a real open item: offer the binding alone.

## Ask only the deltas

One presentation, everything still open in it — tagged keys and plugin toggles together.
They are the same kind of thing now: something a person could answer, that this repo has
not answered. Do not split them into rounds, and do not ask anything the discovery above
resolved.

For each item show:

- **the `hint`**, as the question — it is written for the human, so use its words;
- **the shipped default**, so they can see that saying nothing is already a choice;
- **the fact you checked**, whenever the tag carried a `when` — what you looked at and what
  you found, so the reason this one is even being asked is visible;
- **the exact lines you would write, and to which file**, before any file changes.

Then get a yes, and read-modify-write. For a list key, write only what is being ADDED — the
join does the rest, and `"!reset"` first is how they say the shipped list is wrong rather
than incomplete. `sb plugin list` renders the current enabled-and-bound state if you want
to show it rather than describe it.

If discovery found nothing open, say exactly that and go on to Tier 3.

## Tier 3 — generate a role and preset for what this repo actually is

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

**What a generated QA role is FOR, before you write a word of one.** It is the shipped `qa`
role narrowed to this repo's stack, and the shipped one is not a test runner: an agent that
built a change owns its own tests and builds, and a QA agent exists for the coverage that
agent could not reach itself — another environment, device, account, simulator or
perspective, an end-to-end flow, an integration. Read `sb roles qa` before you draft, and
write the generated role as that job in this repo's terms. Two failure modes to write
against, because a language-named role invites both: "run the test suite" as the whole of
the prompt, which recreates the slow implement-test-return loop the design removed; and
silence about evidence, which gets the author's passing checks run a second time. Say that
what already passed on the commit is read and taken, not repeated.

A generation is THREE files, and the third is the one people forget:

**1. `.switchboard/roles/<name>.md`** — TOML frontmatter fenced by `+++` (not the `---` YAML
fences Claude Code skills use; these are different conventions and crossing them breaks the
file), then the prose that becomes the role's prompt:

    +++
    model = "careful"
    capabilities = []
    +++

    You are the iOS QA agent for this repo, and you are here for what the agent that built
    the change could not reach from a terminal: the app running on a simulator or a device.
    Its tests and its build are its own and already ran on this commit — read that evidence
    and take it. Spend yourself on the screens: exercise the changed flow the way a person
    would, check the adjacent screens for regressions, and say what is still unverified.

`model` must be a tier that already exists — `sb models` prints what actually resolves in
the repo you are setting up, and that listing is the authority; do not invent a tier name
or copy one from another repo. `capabilities` is what an agent of this role may do, as a
list of the strings `sb capabilities` names for this repo — `[]` for a role that only reads
and reports, `["write-tracked"]` for one that edits files git tracks, `spawn` on top of that
for one that may put up agents of its own. (An older `delegate = true`/`false` field is still
read for repos that have one, and means `spawn`; write `capabilities` in anything new.)
There is no `prompt` field: the body after the closing `+++` is the prompt.

**2. `.switchboard/presets/<name>.md`** — plain markdown, no frontmatter. The repo's actual
conventions for that kind of work, in the concrete: the real command, the real simulator or
target, what evidence counts here. A command belongs here, in a file about THIS repo, and
never in a shipped default that would be a lie in every other one.

**3. The binding line** in `.switchboard/presets.toml`, and for a QA role it carries THREE
names, not one:

    [roles]
    ios-qa = ["ios-qa", "verify", "evidence"]

Left side is the role, right side is the presets appended to `all` for it. `verify` and
`evidence` are shipped, and `defaults/presets.toml` binds them to the role literally named
`qa` — a binding is keyed on the exact name, so a generated `ios-qa` gets neither unless you
name them here. Without them the generated role is the only thing telling that agent how to
produce usable evidence, which is how a language-named QA role drifts back into being a test
runner. Without the first line the preset is nameable — `sb presets ios-qa` prints it — and
never reaches an agent. Shipping is not applying.

A generated role that is NOT a QA role takes whichever shipped presets fit the job it does;
the three-name rule above is about QA because that is what this tier generates.

Nothing else is needed to make either file discoverable: both are found by glob, so
`--role ios-qa` works the moment the file is saved.

**Draft, show, confirm, then write.** Put the whole role body and the whole preset in front
of the person before any file exists. You are guessing at their conventions and they are
not — the draft is what makes that guess correctable, and a written file is a thing they
have to review rather than a thing they chose.

Do not author a plugin. Tier 3 is presets and roles: files that are read. A plugin is
Python that runs, and that goes through review and a PR like any other code change.

## Re-runs: offer deltas, diff rather than clobber

Discovery is what makes a second run cheap: the offer-set is recomputed from the files
every time and nothing is remembered between runs. Carry that through to the end:

- **An already-answered key is skipped, not re-asked** — including a list key whose repo
  value names only its additions.
- **A plugin already enabled and already bound is one line of "already done"**, not two
  offers.
- **A generated file that already exists is never overwritten.** Someone has probably
  hand-edited it since — that was the point of generating it. Show the difference between
  what exists and what you would generate, and let the person choose: keep, replace, or
  merge by hand. If nothing differs, say so and move on.

When you have nothing left to offer, say exactly that. "Already set up, nothing to change"
is a complete and correct result for this walkthrough, and is what most re-runs should
produce.
