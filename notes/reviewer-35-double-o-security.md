# Round 4 — SECURITY / untrusted-input review of double-`o` (commit 3c04c14)

Lens: file paths reaching the editor come from an agent's transcript prose (backticked
tokens), which is model-generated and attacker-influenceable. Only that lens. Threading,
crashes, extraction correctness and debounce were rounds 1–3 and are not re-reviewed.

Chain reviewed: `last_assistant_texts` (board.py:1906) -> `report_files` (:1707) ->
`open_report_files` (:1789) -> `_editor` (:1971) / `_inspect` (:1945).

**Verdict: no blocking security defect. Ship.** One real but low finding (symlink
containment bypass, already a consequence of the deliberate no-`resolve()` design), one
latent hardening gap that is not reachable today, and the rest of the attack surface
came back clean under live testing.

---

## What I actually ran

`/Users/andrew/anaconda3/bin/python`, importing `report_files` directly against a
temp worktree containing: a dir symlink out of the worktree, a file symlink out of the
worktree, a file literally named `-g.py`, and a sibling dir `wt-evil` next to root `wt`.

| candidate in backticks | `_PATHLIKE`? | `report_files` returns |
|---|---|---|
| `./-g.py` | yes | `/…/wt/-g.py` (absolute — no leading dash) |
| `-g.py` | no | `[]` |
| `link/secret.md` (dir symlink → outside) | yes | **`/…/wt/link/secret.md` — escapes** |
| `note.md` (file symlink → outside) | yes | **`/…/wt/note.md` — escapes** |
| `../wt-evil/s.py` | yes | `[]` |
| `/…/wt-evil/s.py` (sibling-prefix) | yes | `[]` |
| `../../etc/passwd` | no | `[]` |
| `~/.zshrc` | no | `[]` |
| 300-char basename + `.py` | yes | `[]` (ENAMETOOLONG → caught) |
| `x\x00.py` | no | `[]` |
| `/etc/passwd` | no | `[]` |

---

## (a) ARGV / FLAG INJECTION — **not exploitable**

`_editor("-r", "-g", f)` has no `--` end-of-options separator and no `./` prefix guard,
so on the face of it a file named `-g` or `./-r.py` looks dangerous. It is not, because
of what `report_files` appends: `key = str(joined)` (board.py:1746), where `joined` is
`os.path.normpath(root / cand)` and `root` is the agent's `cwd`. Every emitted path is
therefore **absolute**, and an absolute path can never present as an option token.
Confirmed above: `./-g.py` came back as `/…/wt/-g.py`, not `-g.py`.

**Latent gap, not currently reachable.** The absoluteness is inherited from `cwd`, not
enforced. With `cwd == "."` the same input returns the bare string `-g.py`:

```
report_files(['`./-g.py`'], '.')  ->  ['-g.py']
```

which would land in argv as `cursor -r -g -g.py`. `cwd` comes from `sb inspect --json`,
and every writer I checked stores it absolute (`store.update_agent(..., cwd=str(Path.cwd()))`
at broker.py:914; `cwd=str(self.repo)` at broker.py:1258, 3453; `ws["path"]` at
broker.py:1555). So there is no live exploit. It is one refactor away from being one.

Cheap hardening, if wanted: pass `--` before the path in `_editor`, or assert
`joined.is_absolute()` before appending. I did **not** check whether the configured
editor CLI (`cursor`) honours `--`; that would need verifying before relying on it.

## (b) SHELL INJECTION — **clean**

`grep -n "shell=True|os.system|popen|Popen" switchboard/board.py` returns nothing. Both
subprocess sites are list-form:

- `_editor`: `subprocess.run([_EDITOR, *args], ...)` (board.py:1972)
- `_inspect`: `subprocess.run([sb, "inspect", name, "--json", "-n", "1", "--events", "1"], ...)` (board.py:1958)

No string interpolation anywhere in the command construction. The agent `name` passed to
`sb inspect` is an argv element, not shell text.

## (c) PATH CONTAINMENT BYPASS via symlink — **real, low severity**

Containment is `joined.is_relative_to(root)` on the **normalised** path (board.py:1741),
deliberately not `resolve()`, because `.switchboard` in a worktree is a symlink into the
main checkout and resolving would exclude the very briefs this feature opens. The
documented cost is unavoidable and I confirmed it both ways:

- **Exploit:** agent creates `ln -s /Users/andrew/.ssh evidence` inside its own worktree,
  then writes prose containing `` `evidence/id_rsa.pub` ``. Human presses `oo`.
- **Effect:** `cursor -r -g /…/wt/evidence/id_rsa.pub` — an arbitrary readable file from
  anywhere on the machine opens as a tab, presented as "what this agent wrote".
- `is_file()` follows the symlink, so the existence filter does not stop it. Line:
  board.py:1741–1742.

**Honest severity: low.** No privilege boundary is crossed — the agent that plants the
symlink already runs shell as Andrew and can read the file itself; it gains no access it
lacked. The realistic harm is *display* deception (a file the human reads as agent output
when it is not) plus a nuisance tab. Also note the symlink need not be malicious: an
ordinary symlink in a worktree makes the containment claim in the docstring approximate
rather than exact, which is worth saying out loud somewhere.

Non-symlink escapes are all closed: `..` is collapsed by `normpath` before the check, and
`is_relative_to` is part-based so the classic sibling-prefix trick (`/…/wt-evil/s.py`
against root `/…/wt`) is correctly rejected — both verified above.

## Related, accepted: `_editor(cwd)` opens a folder the agent controls

`open_report_files` opens the worktree itself (board.py:1828) before any file. An editor
opening a *folder* can auto-run workspace config the agent wrote (`.vscode/tasks.json`
with `runOn: folderOpen`, etc.). This is code execution on Andrew's machine triggered by
`oo` — but again the agent already has shell there, so nothing is escalated. Recording it
because it is the sharpest thing in this chain, not because it needs a fix.

## (d) NULL BYTES / NEWLINES / OVERLONG / `..` — **all clean**

- **Null byte:** rejected twice over. `_PATHLIKE`'s `[\w./-]` does not match `\x00`, and
  even if it did, `is_file()` raises `ValueError` into the `except (OSError, ValueError)`
  at board.py:1743. Verified: `x\x00.py` → `[]`.
- **Newline:** `_BACKTICKED`'s `[^`]+` **does** span newlines (verified:
  ``_BACKTICKED.findall("`a.py\nb.py`")`` → `['a.py\nb.py']`), so a multi-line span is
  captured. It is then rejected by `_PATHLIKE`, whose char class excludes `\n`, with `^`/`$`
  anchoring — and a trailing newline is gone by `.strip()` first. No candidate with an
  embedded newline survives.
- **Overlong:** no explicit length cap, and none needed. A 300-char basename matches the
  regex, then `is_file()` fails ENAMETOOLONG → `OSError` → caught. Verified: `[]`. Longer
  than PATH_MAX behaves the same. Any surviving path must be a real file, so the OS bounds it.
- **`..`:** collapsed by `normpath` before the containment check, so it can only move the
  path *out* of root and be rejected. Verified.
- **`~`:** `_PATHLIKE` admits only a literal `~/` prefix, and `~/…` then fails containment
  unless it genuinely lands under the worktree. `~root/x.py` does not match the regex at all.
- **Device/FIFO:** `is_file()` is `S_ISREG`, so `/dev/*` char devices and named pipes are
  filtered out. Worth noting, since handing a FIFO to the editor would hang it.

## Trivial: unbounded candidate scan

`report_files` stats every path-shaped backticked token in the last 3 assistant texts;
the `limit` early-return only fires once 6 *match*. An agent emitting tens of thousands of
path-shaped-but-nonexistent tokens buys tens of thousands of `stat` calls. Off the drawing
thread, bounded by transcript size, sub-second. Not worth a change; noted for completeness.

## What I did not check

- Whether `cursor`'s CLI actually honours a `--` separator (only relevant if the hardening
  in (a) is adopted).
- The `sb inspect` side beyond argv construction — `name` is board-supplied, not
  transcript-derived, so it is outside this lens.
- Any non-`cursor` value of `editor.command`; a shell-wrapper editor would inherit
  whatever quoting that wrapper does, which I have not audited.
