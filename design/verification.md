# Verification of `PLUGIN-REDESIGN.md` against the code

Read-only pass. Every factual claim in the design of record about the *existing* codebase,
checked against source. Nothing was changed.

**Result: 1 WRONG, 1 STALE-BY-DOCUMENTATION, 0 UNVERIFIABLE. The rest hold.**

The one WRONG claim is a supporting sentence inside §5.4 reason 1. **It does not sink §5.4**
— reasons 2 and 3 carry that section unaided, and reason 2 is in fact strengthened by what
the code actually does. Details in "The WRONG claim" below.

**Tree checked:** this worktree, `plugins-redesign` @ `86fac25`
(`~/.herdr/worktrees/switchboard/plugins-redesign`), which is the initial
commit and is **behind** `main`. `main` moved twice *during* this verification
(`5bb4b79` → `2637b5f`). Where main or `workspace-model` changes the substance, it is
called out per row and in the two sections at the end. Line numbers below are this
worktree's unless stated.

---

## 1. The load-bearing claims (brief §1–12)

| # | claim | supports | verdict | real citation |
|---|---|---|---|---|
| 1 | `store.repo_root()` returns the shared `.git`, byte-identical from every worktree; cwd-anchoring is real | §5.1 (entire), §2, §5.2 | **CONFIRMED** (line-exact, and empirically) | `store.py:44-59` |
| 2 | `Broker.delegate` assembles protocol → identity → workspace → (`--as` OR role prompt) → `with_`; `--as` replaces only the role prompt and never touches `with_` | §6 (rejects proposal A's slot-2) | **CONFIRMED** (line-exact) | `broker.py:897-907`; `as_prompt` at `:903-906`, `with_` at `:907` |
| 3a | `_SCHEMA_HASH` is a sha256 over the entire `SCHEMA` string, so any added table bumps it for all tables | §5.4 reason 2 | **CONFIRMED** | `store.py:176` (over `SCHEMA`, `store.py:127-174`; truncated to 16 hex chars) |
| 3b | the store is "documented disposable" | §5.4 reason 1 | **CONFIRMED as documentation, but the documentation is stale** | docstring `store.py:191-196`; contradicted by `_migrate_additive`, `store.py:242-268`. **Deleted outright on current `main`** — see §5 |
| 3c | *(the design's gloss)* "A todo list that vanishes when sb adds a column is not a todo list" | §5.4 reason 1 | **WRONG** | `store.py:257-264` — an added column is the one case that migrates in place |
| 4 | `config.merge()`: tables merge key-by-key, arrays join base-first de-duplicated, `"!reset"` first discards the base | §7.3, §7.4 escape hatches, §11.7 | **CONFIRMED** (line-exact, and empirically through the real load path) | `config.py:170-183` (`merge`), `:186-194` (`join`), `:197-202` (`_dedupe`), `RESET` at `:55`; load path `config.py:414-425` |
| 5 | `plugins.available()` reads `defaults/plugins/*.md` on every call, so shipped presets are nameable from a repo with no `.switchboard/plugins/` | §7.1 (entire) | **CONFIRMED** (line-exact, and empirically) | `plugins.py:49-63` |
| 6 | `config.flatten()` / `validate.line()` — headings dropped, bullets joined with `; `, whitespace collapsed, no newlines reach herdr | §6 | **CONFIRMED** (line-exact, and empirically) | `config.py:216-232`; `validate.py:104-119` |
| 7 | `Broker.ask()` refuses `sb ask human` and points at `sb block` | §8.3.1 (the live bug) | **CONFIRMED** (line-exact) | `broker.py:1026-1033` |
| 8 | three tests fail by construction | §8.1 row 9, §3.2 | **CONFIRMED** (all three line-exact) | `tests/test_status.py:750` (in the `sample` dict; the exact-verb-set assert is `:756`); `tests/test_validate.py:253`; `tests/test_config.py:345` |
| 9 | `--live`/`--active` and `--all-idle`/`--include-kept` each share one `dest` | §3.2 precedent argument | **CONFIRMED** (line-exact) | `cli.py:157`, `cli.py:190` |
| 10 | `_tier_help()` wraps a config read in a bare `except Exception` | §4.5 (against dynamic parser registration) | **CONFIRMED** (substance exact; function starts at 56, not 60) | `cli.py:56-71`; the bare `except Exception:` is `cli.py:69-70` |
| 11 | `store.log_event` is a generic `(agent, kind, JSON)` append log taking new kinds with no schema change | §4.4 (Logging) | **CONFIRMED** (line-exact) | `store.py:638-650`; `events` table `store.py:166-173` |
| 12 | `cli.py:399-401` renders `ValueError`/`KeyError` as claimed | §4.6 | **CONFIRMED** (line-exact) | `cli.py:399-401`, inside `main` (`cli.py:361`), via `_reason` (`cli.py:404`) |

### Empirical results for claim 1

Run from three checkouts of one clone:

| standing in | `worktree_root()` | `repo_root()` |
|---|---|---|
| `~/Code/switchboard` | `~/Code/switchboard` | `~/Code/switchboard/.git` |
| `~/.herdr/worktrees/switchboard/plugins-redesign` | `…/plugins-redesign` | `~/Code/switchboard/.git` |
| `~/.herdr/worktrees/switchboard/acc-kid` | `…/acc-kid` | `~/Code/switchboard/.git` |

Byte-identical: **true**. §5.1's table is reproduced exactly.

The anchoring is load-bearing and I proved it rather than took the comment's word:
`git rev-parse --git-common-dir` returns the **absolute** path from inside a worktree, but
the bare relative `.git` from the main checkout. Called as `repo_root(Path("~/Code/switchboard"))`
with the *process* cwd set to `/tmp`, it still returns `~/Code/switchboard/.git`;
a plain `.resolve()` would have returned `/private/tmp/.git`. `store.py:54-59` is doing real
work, exactly as its comment says.

---

## 2. Uncited assertions about today's behaviour

All checked; all hold unless noted.

| claim | section | verdict | citation |
|---|---|---|---|
| six presets ship: `adversarial`, `ask-dont-guess`, `evidence`, `own-files`, `report-bug`, `verify` | §1 | **CONFIRMED** | `defaults/plugins/` |
| a preset has no front matter; its name is its filename stem | §1 | **CONFIRMED** — `front_matter` is used only by the roles loader | `plugins.py:62` (`f.stem`); `config.front_matter` called only at `config.py:343` |
| an unrecognised `--with` value is passed through verbatim as a literal instruction | §1, §3.3, §8.1 rows 3–4, §8.3.2 | **CONFIRMED** | `plugins.py:94-110`, the `else` at `:108-109` |
| `plugins.toml` binds names to roles via `all` + `[roles]`; shipped bindings are empty | §1, §7.1, §8.1 row 5 | **CONFIRMED** | `defaults/plugins.toml` (`all = []`, empty `[roles]`); read at `config.py:414-425` |
| `sb plugins` lists names with their bindings | §1 | **CONFIRMED** | `cli.py:556-566` |
| the only occurrence of `"plugins"` as a payload key is the producer; nothing consumes it; `scripts/` never invokes `sb plugins` | **§3.2 (the fact-check)** | **CONFIRMED** | producer `cli.py:565`. Other `"plugins"` literals are `plugins.py:58` (a directory name), `cli.py:163` (the verb), `cli.py:556` (the dispatch branch). `scripts/`: zero hits. Only `notes/FEATURES.md` mentions the verb, in prose |
| `plugins.py`'s module docstring says plugin files are not layered out of `defaults/`, and the survey's summary overstates the rule | §7.1 | **CONFIRMED, and sharper than stated** | module docstring `plugins.py:15-19` says "not layered out of `defaults/`"; `available()`'s **own** docstring at `plugins.py:52-53` says "Layered like everything else in `defaults/`". The file contradicts itself, and the code sides with §7.1. Survey text at `plugins-current-state.md:85` and `:91` |
| `--with` values are validated by `validate.line()` after resolution | §6 | **CONFIRMED** | `cli.py:483-484` (this worktree); moved to `broker.py` on `workspace-model` — see §5 |
| `cli.py`'s docstring is proud of naming the flag the caller typed | §4.3 | **CONFIRMED** (line-exact) | `cli.py:16-18` |
| `sb board` is hidden, and refused for an agent caller | §4.3 | **CONFIRMED** | `cli.py:110-115`, refusal at `cli.py:449-453` |
| `sb workspace new` is already a nested subparser | §3.1 | **CONFIRMED** | `cli.py:197-199` |
| the doorbell-flush precedent: catch, `store.log_event`, one line, carry on | §4.2 | **CONFIRMED** (quote is at `:388`, mechanism at `:389-392`) | `cli.py:388-392` |
| `config.json` lives beside the store, deliberately not a table in it, because the database is disposable | §5.4 (the precedent) | **CONFIRMED** (line-exact) | `store.py:85-87` |
| there is no extension point — a plugin's table would have to be spliced into the one `SCHEMA` string | §5.4 reason 3 | **CONFIRMED** | `SCHEMA` is a module-level literal, `store.py:127-174`; `_wanted()` re-parses that literal, `store.py:225-239`. Nothing registers, nothing appends |
| repo state path is `<shared .git>/agentflow/…` | §5.2, §8.1 row 6 | **CONFIRMED** | `paths.store_dirname = "agentflow"`, `defaults/settings.toml`; `store.py:41`, `:79` |
| `[limits] prompt = 8000` covers presets and role prompts | §6 (Budget) | **CONFIRMED** | `defaults/settings.toml` `[limits] prompt = 8000`, whose own comment names "plugin files after flattening" |
| `protocol.md`'s header says its contents are "paid for on every single spawn, by every agent, forever" | §6 (Budget) | **CONFIRMED**, mild paraphrase | `defaults/protocol.md:2-4`. The file's exact sense is that HTML comments are *free* and "everything outside it is paid for on every single spawn, by every agent, forever." The design's rendering is substantively right |
| `ask-dont-guess.md` tells agents to run `sb ask human` | §8.3.1, §8.1 row 7 | **CONFIRMED — and incomplete, see below** | `defaults/plugins/ask-dont-guess.md`, last paragraph |
| `report-bug.md` currently tells agents to append to `notes/BUGS.md` | §10 | **CONFIRMED** | `defaults/plugins/report-bug.md` |
| `store.transcript_path()` yields the full Claude Code transcript | §10 | **CONFIRMED** (line-exact) | `store.py:668-678` |
| shipped plugins are testable today via the `sys.path` arrangement `bin/sb` uses | §11.13 | **CONFIRMED** | `bin/sb:3` |
| §4.2's level-0 verb list is the real verb set minus `presets`/`delegate`/`doctor`/`plugin list` | §4.2 | **CONFIRMED** — 17 + 3 = the 20 verbs the parser actually has | `tests/test_status.py:747-756` enumerates all 20 and asserts the set |
| the transition can tell a pre-rename `plugins.toml` from an enablement one because the keys are disjoint | §8.2 | **CONFIRMED** | reader takes only `all` and `roles` (`config.py:423-424`); `enabled` is a free key, and `merge()` handles a file containing both |

---

## 3. The WRONG claim

### §5.4, reason 1 — "A todo list that vanishes when sb adds a column is not a todo list."

**What the code actually does.** `connect()` does not drop on every schema-hash mismatch.
It calls `_migrate_additive()` first, and only falls through to `_reset()` when the change
is genuinely non-additive (`store.py:210-217`). `_migrate_additive` (`store.py:242-268`)
does exactly what its name says: for each table in `SCHEMA`, any column present in the
source and missing from the store is added with `ALTER TABLE … ADD COLUMN`
(`store.py:257-264`), and the hash is re-stamped. **Adding a column is the paradigm case
that survives, not the paradigm case that wipes.** The comment at `store.py:211-215` says
so in its own words, and cites the incident that motivated it.

The quoted docstring — "There are no migrations… on a schema change we simply drop and
recreate" (`store.py:193-195`) — is therefore **stale prose sitting eight lines above code
that migrates.** The design quoted it faithfully; the docstring is what is wrong. Which
means claim 3b is confirmed as a quotation and worthless as evidence.

**Which design section is unsound, and how badly.**

§5.4 is a three-reason argument for keeping plugin state out of `state.db`. Reason 1 is the
casualty, and only partly:

- Its *premise* ("documented disposable") is true of the documentation and false of the code.
- Its *illustration* ("vanishes when sb adds a column") is flatly false.
- Its *conclusion* — a plugin's durable data must not live somewhere that can be dropped —
  **still stands**, because a non-additive change still reaches `_reset()`, and a whole new
  table is classified non-additive by name (`store.py:250-253`).

**Reason 2 is untouched and is actually stronger than the design claims.** Splice a `todos`
table into `SCHEMA` and, against any pre-existing store, `_migrate_additive` hits
`table not in {…}` → returns `False` → `_reset()` drops `agents` and `messages` along with
it. The design says a plugin's table "would force the reset-or-migrate decision" for the
other tables. It is not a decision; it is an unconditional reset. §5.4's headline
("A todo list must not be able to threaten the agent table") is correct and the code makes
the threat sharper than the text does.

**Reason 3 is untouched.** There is no extension point; `SCHEMA` is a literal.

**Blast radius: one sentence, not one section.** §5.4's ruling, §5.2, §5.3, §5.5, §5.6, and
the §12 row-8 adjudication all survive unchanged. What needs rewriting is reason 1's two
sentences, and they should be rewritten to lead with reason 2's mechanism rather than with
a docstring that the module has outgrown. Anyone building from §5.4 as written will cite a
docstring that **no longer exists on `main`** (see §5).

---

## 4. Two things the design says that the code does not disagree with, but that will bite

Neither is a false claim. Both are places where an implementer following the document will
find the code is not shaped for what §6 and §8.3 ask.

**(a) §6's asymmetric failure rule has no provenance to work with.** §6 rules that a
fragment reached *via a binding* which fails to resolve is **skipped with a warning**, while
one named *explicitly on the command line* is an **error**. `plugins.for_role()`
(`plugins.py:80-91`) flattens the every-agent bindings, the role's bindings, and the
caller's `--with` into one undifferentiated `list[str]`, and `plugins.resolve()`
(`plugins.py:94-110`) receives only that flat list. By the time resolution happens, *which
layer a name came from is gone.* Implementing §6's rule requires changing `for_role`'s
return type. This is true in this worktree (`cli.py:478`) and remains true on
`workspace-model` (`broker.py:1116`). The design does not mention it.

**(b) `report-bug.md` carries the same `sb ask human` bug that §8.3.1 fixes in
`ask-dont-guess.md`.** `defaults/plugins/report-bug.md` ends with "If the bug blocks you
entirely, run `sb ask human` instead" — the identical dead command. §8.3.1 and §8.1 row 7
name only `ask-dont-guess.md`. §8.3.2 does rewrite `report-bug.md` wholesale, so the bug
would likely be swept up incidentally, but the design's own break list undercounts the
occurrences by one and a reader working from §8.1 row 7 will fix one file and leave the
other.

**(c) minor, §4.6.** "a reserved exit code, matching how `cli.main` renders
`ValueError`/`KeyError` today (`cli.py:399-401`)". The *rendering* matches (`sb: <reason>`
on stderr). The *exit code* does not: `cli.py:401` returns `1`, and there is no reserved
code today. A reserved code would be a departure from the cited precedent, not a match to it.

---

## 5. What the in-flight work is about to invalidate

The repo moved further than the brief described, and it moved **during this verification**.
`main` was at `5bb4b79` when I started and at `2637b5f` when I finished.

### 5.1 `main` @ `2637b5f` — "store: the schema hash is a cache key, not a version"

This is the big one. It lands directly on §5.4 and it is already merged to `main`.

On `main` today:

- The docstring §5.4 reason 1 quotes is **gone**. `connect()` now opens with "Open the
  store, reconciling the schema as needed. **NEVER raises over a schema change.**"
  There is no longer any sentence in `store.py` saying "there are no migrations… we simply
  drop and recreate." §5.4's citation `store.py:190-195` will not resolve to anything
  supporting the claim.
- `_SCHEMA_HASH` now carries an explicit comment demoting it: "**A cache key, NOT a
  version.** … It now means only 'the store was last stamped by different source text, go
  and look at its actual shape'. Compatibility is decided by `_deficit`, which asks whether
  the store *contains* what this code needs." So §5.4 reason 2's mechanism — *the hash bump
  is what forces the decision* — is no longer the operative mechanism.
- `_migrate_additive` is replaced by `_reconcile` / `_deficit` / `schema_deficit`, with a
  third outcome the design has never heard of: **degraded-but-serving**. When a rebuild is
  needed and agents are live, the old store is left open and *unstamped*, and the rebuild
  is deferred to whichever `sb` runs after the fleet drains.

**Net effect on §5.4:** the *conclusion* survives — `_deficit` still classifies a missing
table as `blocking`, and `_reconcile` still calls `_reset()`, so splicing a plugin table
into `SCHEMA` still drops `agents` and `messages`. But **both of §5.4's cited supports are
now dead on `main`**: reason 1's quotation no longer exists, and reason 2's "one hash covers
all tables" is contradicted by a comment written specifically to say the hash decides
nothing. §5.4 must be re-grounded on `_deficit`'s missing-table branch before anyone builds
from it. The design's substantive position is right; its evidence has expired.

Also relevant: §8.1's non-breaking row "`state.db` and its schema — **unchanged**, no
schema-hash bump, no reset" is *more* comfortably true under `main`'s new reconciler than it
was under the old one, since a comment edit no longer triggers anything.

### 5.2 `workspace-model` @ `7ec6770` — plugin resolution moves into `Broker.delegate`

Commit `609bb4b` ("Resolve plugin bindings in `Broker.delegate`, not the CLI"), later
renamed by `2b80af8` to `Broker._resolve_bindings`.

**What survives:**

- **Claim 2 survives intact.** The assembly is unchanged — protocol → identity → workspace →
  (`--as` OR role prompt) → bindings — at `broker.py:1233-1243` instead of `897-907`.
  `--as` still lands at the role-prompt slot only and still never touches the bindings list.
  §6's rejection of proposal A's slot-2 is safe. **DRIFTED, substance holds.**
- The `validate.line(..., "plugin text")` post-resolution check moves with it
  (`broker.py:1117-1118`), so §6's flattening/validation pipeline is unchanged.

**What breaks:**

- **§4.2's level table is wrong for `start` and `workspace`.** The table puts `start`,
  `workspace`, `board`, `restore` and the rest at **level 0 — "nothing"** — and reserves
  level 2 (glob the roots, read a `.md`, flatten) for `delegate` alone. The whole point of
  `609bb4b` is that `sb start` and `sb workspace new` reach `Broker.delegate` *directly*,
  and after it they too resolve bindings. On `workspace-model`, **`start` and
  `workspace new` are level-2 verbs.** The commit message says so explicitly: those two
  paths previously "produced agents with no plugin bindings at all," and that was the bug
  being fixed.

  The *safety* property §4.2 actually cares about is unharmed — level 2 still never
  imports plugin code, so a broken plugin still cannot break `sb start`. §4.6 test 1 still
  passes. But the table is a stated, "fixed and testable" assignment of verbs to levels,
  and two of its level-0 entries will be wrong the moment `workspace-model` lands. The
  table needs `start` and `workspace` moved to level 2, and §4.6 test 1 needs them tested
  as level-2-with-a-broken-plugin rather than level-0.

- **§4.2's sentence "`sb status`, `sb done`, `sb ask`, and every other core verb never even
  glob" needs narrowing** to exclude the two spawn paths.

- **`Broker` gains a dependency on `plugins`.** `workspace-model` adds
  `from . import plugins as plugins_mod` to `broker.py`. The comment the design's topology
  leans on — the old `cli.py:475-476`, "Layered here, not in the broker: the broker takes
  prompt strings and knows nothing about plugins, so the vocabulary can change without
  touching it (C13)" — is **deleted** by `609bb4b`. Anything in the design that assumes the
  broker is plugin-ignorant should be re-read against that.

- `ef1ab97` adds an `agents.branch` column to `SCHEMA`. Harmless for the design (it is
  exactly the additive case), but it is a live example of the schema moving under whatever
  §5.4 ends up saying.

### 5.3 `8c5251d`

Touches `defaults/roles/orchestrator.md` only. No design claim depends on it.

### 5.4 A note on the moving target

`main` advanced mid-verification. Everything above was checked against
`plugins-redesign@86fac25` for the primary verdicts and against `main@2637b5f` /
`workspace-model@7ec6770` for the drift sections. If `main` has moved again by the time
this is read, §5.1 is the row most likely to have moved with it — it is the one an active
branch is currently rewriting.

---

## 6. Summary

- **12 of 12 load-bearing claims: substance holds.** Ten are line-exact. One (`_tier_help`)
  is off by four lines at the function head with the substance inside the cited range. One
  (§5.4 reason 1) is confirmed as a quotation and unsound as evidence.
- **1 WRONG:** §5.4 reason 1's illustration — an added column migrates in place, it does not
  wipe. §5.4's conclusion survives on reasons 2 and 3.
- **§5.1 is the strongest-supported section in the document.** Every element of it,
  including the worked table, reproduces exactly and was verified by running the code from
  three checkouts.
- **§3.2's fact-check — the one thing the brief said was already caught — is correct.** There
  is no `--json` consumer of the `plugins` key anywhere in the repo.
- **The one thing to fix before building: §5.4's evidence.** Both of its citations are dead
  or demoted on current `main`. Re-ground it on `_deficit`'s missing-table branch.
- **The one thing to fix in the plan: §4.2's level table**, which `workspace-model` makes
  wrong for `start` and `workspace`.
