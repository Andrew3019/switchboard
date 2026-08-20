# reviewer-32 — correctness review of `0dadb02` (double-`o` opens worktree + report files)

Lens: correctness of path extraction and the double-press debounce ONLY.
Not reviewed: security, subprocess robustness, UX.

**Verdict: needs changes.** Three concrete defects, all reproduced against real data
or a real pty. The feature's stated contract ("the files the agent WROTE, opened on a
double press") fails in both halves on ordinary inputs.

---

## 1. Line-range citations are stripped and then OPENED — the opposite of the stated rule

`switchboard/board.py`, `report_files` / `_LINE_SUFFIX`.

The module comment above `_BACKTICKED` says:

> `board.py:1914-1929` is a citation, not a file to open, and the line range is what says so.

The code does the reverse: `_LINE_SUFFIX.sub("", span)` **removes** the marker that
identified the citation, so the citation then passes `_PATHLIKE` and the existence
check and is opened.

Reproduced (cwd = this checkout):

```
board.report_files(["the left-click handler (`switchboard/board.py:1914-1929`) does it"], cwd)
-> ['/…/switchboard/board.py']
```

The test `ReportFilesTest.test_a_written_file_is_opened_and_a_code_citation_is_not`
asserts `[]` for exactly this input, but passes only because `board.py` does not exist
under the tmp cwd it uses. It exercises the existence filter, not the citation filter.
Drop `board.py` into the tmp dir and the assertion fails.

Consequence, measured on real transcripts (8 most recent `~/.claude/projects/*switchboard*`
sessions, cwd = this worktree): 3 of 8 would open `DESIGN-TRUTH.md`. In one of them the
matched prose is literally

> `**`DESIGN-TRUTH.md` untouched** (Andrew-only).`

i.e. the agent stated it did not write the file, and the feature opens it as a tab.
`DESIGN-TRUTH.md` is the doc agents are forbidden to edit — the single worst false
positive available.

Either the strip should be a *reject* (a line range means citation), or the comment and
test name are wrong about what the strip is for. As written the code and the prose
disagree, and the test does not settle it.

## 2. The cap-6 is applied oldest-first, so the newest message's report file is dropped

`report_files` iterates `texts` in the order `last_assistant_texts` returns them
(oldest first) and `return`s the moment `len(out) >= limit`. The message most likely to
name the report — the final summary — is the last one scanned.

Reproduced:

```
old = "I read `notes/a.md` … `notes/f.md`"       # 6 files, merely read
new = "Done. Findings in `notes/THE-REPORT.md`."
report_files([old, new], tmp) -> [a,b,c,d,e,f]   # THE-REPORT.md never reached
```

Six read-only citations in one earlier message are enough to evict the one file the
feature exists to open. Combined with finding 1 this is not a corner case: prose that
cites six files is normal for a reviewer or a lead. Scanning newest-first (and reversing
at the end if display order matters) fixes it.

## 3. Two `o` presses coalesced into one terminal read never fire

`switchboard/board.py`, main loop: `if "o" in ev["raw"]: fire, last_o = double_press(...)`.

`parse_sgr` lumps a whole run of non-mouse bytes into ONE event, so `raw` can be `"oo"`.
`in` is a membership test, not a count, so two presses inside one read count as one press
and nothing happens.

Reproduced, board's own parser:

```
board.parse_sgr("oo") -> ([{... 'raw': 'oo'}], '')     # one event
```

Reproduced, real pty in raw mode (the board calls `tty.setraw`): two writes 20 ms apart,
read after 50 ms of the loop being busy →

```
one read got: b'oo'
```

The loop *is* regularly busy for tens of ms: `refresh(sup)` + `draw()` on the REFRESH
tick, and `open_report_files` itself blocks on an `sb inspect` subprocess. Key auto-repeat
(holding `o`) is the same failure, permanently — the whole burst is one event.

Symptom for the user: `oo` intermittently does nothing. Worse follow-on — the swallowed
pair still sets `last_o`, so a single stray `o` up to a second later fires the editor.

Fix: act on `ev["raw"].count("o")` presses, not on membership.

---

## Checked and found correct

- **Debounce arithmetic.** Single press does not fire. Exactly 1.000 s apart does not
  fire (`<`, matching "inside a second"); 0.999 s fires. Three fast presses fire once —
  reset-to-0.0 makes the third the first half of a new pair, as documented.
- **Different rows.** The debounce holds no row identity, but the highlighted row is
  `where.name(...)` (the pane's neighbour) and is not moved by keys or by clicks any
  more, so there is no stale-row pairing. Firing on whatever is highlighted at the second
  press is the right behaviour.
- **Dedupe** on the resolved path string — correct, including two spellings of one file.
- **Empty transcript / no text blocks / missing file / torn last line** — all return `[]`
  without raising (`last_assistant_texts`); verified against a real 400-record tail.
- **URLs** — `startswith("http")` plus the existence check; `www.…/a.md` survives the
  regex but dies on the filesystem.
- **Trailing punctuation** — `` `notes/x.md.` `` is rejected (`\.[a-zA-Z0-9]{1,5}$`).
- **Backticked commands with spaces** (`git show … board.py`) are rejected by `_PATHLIKE`.

## Lesser findings (real, low impact)

- **Absolute paths are silently dropped.** `_PATHLIKE` starts `^[\w.]`, so a leading `/`
  fails. Verified: `report_files(["wrote `/…/README.md`"], cwd) -> []`. Agents in this
  repo are told to point at evidence precisely and often write absolute paths.
  `Path(root) / "<absolute>"` already resolves correctly in Python, so allowing it is a
  one-character change. `~/x.md` is dropped for the same reason (and would need
  `expanduser`).
- **Extension-less files are dropped** — `` `bin/sb` ``, `` `Makefile` `` fail the
  mandatory `\.`.
- **Paths with spaces are dropped** — `` `notes/a b.md` `` fails `[\w./-]*`. Rare; noting
  it because it was asked.
- **"under the agent's cwd" is not enforced.** The docstring claims the deciding filter is
  existence *under* cwd; `resolve()` + `is_file()` does not constrain the prefix.
  Verified with cwd=`switchboard/`: `` `../README.md` `` resolves out of cwd and is
  returned. Contained in practice (`..` needs a dotted extension to survive `_PATHLIKE`),
  but the doc overstates the guarantee.
- **`limit=0` returns one file**, not zero — the cap is checked after the append. Not
  reachable from the board.
- **`time.time()` is not monotonic.** A backward clock step between two presses makes
  `now - last` negative, which is `< window`, so a *single* `o` fires the editor.
  `time.monotonic()` is the right clock for a debounce.
- **`_TRANSCRIPT_TAIL = 400` can under-deliver.** On a real transcript only 7 of the last
  400 records carried text blocks; a long tool run can leave fewer than `n=3`. Degrades
  gracefully (fewer files), so noted, not a defect.

## How to reproduce

All of the above was run from the worktree root with
`/Users/andrew/anaconda3/bin/python`, importing `switchboard.board` directly and calling
`report_files` / `double_press` / `parse_sgr`. The pty proof uses `pty.openpty()` +
`tty.setraw` + `select` + `os.read`, mirroring the board's own loop. I did not run the
board interactively and did not exercise `open_report_files`' subprocess paths (out of
lens).
