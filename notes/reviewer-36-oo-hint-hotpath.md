# Review — the `oo` hint's hot path, cache and fork (c329b0c, on edae828)

One lens only: the code new in c329b0c — `Reports`, `hint_lines`, `locate`,
`files_for`, `_mtime`, and the hint's rendering in both `layout`s. The `oo` open
handler, extraction correctness and earlier rounds' territory were out of scope
and I did not look at them.

**Verdict: needs changes.** One user-visible layout regression on the rich board,
one wrong-agent race in the cache, and one hole in the fork throttle. The hot path
itself is sound: with a stable transcript the board forks once and then costs one
`stat` a frame, which I measured.

---

## 1. Rich renderer: the hint takes its two lines OFF THE TREE, not out of the slack

`switchboard/richboard.py:588-595`

```python
room = (capacity - head_lines - 1 - len(needs) - gap_min - len(below)
        - len(hint))
if room < 1 and hint:
    room += len(hint); hint = []
```

`room` is what the tree's window is sized against, so the hint is charged to the
tree *unconditionally* and only handed back when the pane is already down to its
last line. The plain renderer does the opposite and matches the stated intent —
`board.py:1318-1325` pads out of the slack and drops the hint only if it does not
fit — so the two renderers disagree, and the one that disagrees is the rich one.

Trigger — 12 agents, height 20, width 70, `here="w0"`:

```
with the hint            without the hint
 w0 … w7                  w0 … w9
 + 4 more below           + 2 more below
 w0 wrote 2 files you can open
 press oo for them in cursor
```

Effect: on any tree that already overflows, two agents drop below the fold to make
room for a line about a keystroke. Worse, the hint appears the moment the
highlighted agent names a file and vanishes when it stops, so the tree jumps by two
rows on its own while a human is reading it.

Swept heights 6-39 x 1/2/5/12/30 agents x 0/1/4 blocked, both renderers: the plain
renderer loses **no** tree rows to the hint at any size; the rich one loses two at
every height where the tree overflows (h=14..39 at 30 agents, h=14..22 at 12).

Shape of the fix: size the window without the hint, then drop the hint if what was
actually drawn leaves no slack for it — i.e. the plain renderer's rule.

Not a click-safety problem: owners are carried per line, so the rows that remain
still map correctly.

## 2. Torn read — agent A's hint can show agent B's file count

`switchboard/board.py:1959-1960` (writer) and `1942` (reader)

```python
self._files = files_for(cwd, transcript)
self._key = (name, _mtime(transcript) if transcript else None)
...
return self._files if self._key and self._key[0] == name else []
```

Two variables, two assignments, no lock. Between them `self._files` belongs to the
new agent while `self._key` still names the old one, and the reader's guard passes.
The window is not a bytecode boundary — it is a whole `os.stat` inside `_mtime`,
which is a syscall and a preemption point.

Reproduced (`_mtime` delayed on the worker thread only, two agents, A has 1 file and
B has 7):

```
settled on A ->                        ['A wrote 1 file you can open', ...]
highlight back on A, mid-recompute ->  ['A wrote 7 files you can open',
                                        'press oo for them in cursor']
```

Sequence: highlight sits on A; the human switches tab to B, which starts a recompute;
the human switches back to A before it finishes.

Severity is low — a wrong count for a frame or two, and `oo` itself re-`locate`s and
opens A's real files, so nothing wrong is *opened*. But it is the one thing the hint
must not do, and the fix is one line: publish `(key, files)` as a single tuple
assignment and read it once.

## 3. The "one fork a minute per agent" bound does not hold for an agent with no transcript

`switchboard/board.py:1950`

```python
if (located is None or not located[1]
        or time.monotonic() - located[2] >= _REPORTS_RECHECK):
```

`not located[1]` short-circuits the age check, so an agent that `sb inspect` reports
with a `cwd` and no transcript re-forks on **every** recompute — the cached
`located[2]` timestamp is ignored on exactly the path it exists for.

Single-agent case is safe: the key stays `(name, None)`, so only the 60 s `due` path
fires. It goes wrong as soon as the highlight alternates, because a change of agent
forces a recompute regardless of age. Measured, with `locate` stubbed and counted:

```
one agent, stable transcript, 50 frames   -> 1 locate call
10 flips between A and a transcript-less agent, 0.16 s -> 11 locate calls
                                              (10 of them for the transcript-less one)
```

So the fork rate is bounded by how fast a human changes tmux tab, not by
`_REPORTS_RECHECK`. In practice that is a few forks a second at worst, not a freeze —
the recompute is off the drawing thread and `_busy` serialises it — but it is not
what the design claims, and the `_REPORTS_RECHECK` docstring ("a transcript that did
not exist when the board first looked is picked up within that and nothing is asked
again in between") is false on this path.

Fix: check `located[2]`'s age whether or not there is a transcript.

## 4. Nits

* `Reports.tick`'s docstring says "never raises", but `_busy` is set to `True`
  *before* `threading.Thread(...).start()`, and `start()` raises `RuntimeError` when
  threads cannot be created. That would both crash the draw loop and wedge the hint
  permanently — `_recompute` swallows `BaseException` for precisely this reason and
  `tick` does not. Trigger is thread exhaustion only, so: unlikely, cheap to close.
  (`board.py:1940-1941`)
* `_mtime` runs on the drawing thread and catches only `OSError`. Its argument is
  `detail.get("transcript")` — whatever `sb inspect --json` emitted. A non-string
  would raise `TypeError` straight into the draw loop (and an `int` would silently
  `stat` a file descriptor). Same exposure the old code had via `Path(transcript)`;
  it is now per frame rather than per keypress.

---

## What is clean

* **The hot path.** 50 frames on one agent with a stable transcript = 1 fork, then
  one `stat` and a dict lookup per frame. Verified by counting.
* **A transcript whose mtime moves every couple of seconds recomputes without
  forking** — the cache does the job it was built for.
* **The recompute cost is not the problem I expected.** `last_assistant_texts` on a
  real 15 MB transcript: 8-21 ms, page-cache warm. Re-parsing every 2 s while an
  agent writes is affordable, and it is off the drawing thread.
* **Frame height.** Exactly `height` lines with and without the hint, across
  heights 6-39, 1-30 agents, 0-4 blocked, both renderers. No off-by-one, the footer
  is never truncated, and NEEDS YOU is never displaced by the hint.
* **`_recompute` cannot take the board down.** `BaseException` caught, `_busy`
  cleared in `finally`.
* **No stale cross-agent hint from the cache itself** — `_key[0] == name` is the
  right guard; only the non-atomic publish in finding 2 defeats it.
* **`locate` / `files_for` shared by hint and keypress**, so the promised count and
  the opened files come from one definition.

## (e) The static footer, confirmed intentional

`click a row to focus it · scroll to pan · oo opens files · a archived · q quits`
lost its `oo` clause, and nothing replaced it. Worth naming precisely: the hint needs
`here`, `here` comes from `Locator`, and `Locator` is disabled when `HERDR_TAB_ID` is
unset (`board.py:1503`, `panes` stays `[]` so `name()` is `None`). So a board run
outside herdr — `python -m switchboard.board` — can never show the hint, and now
advertises `oo` nowhere at all. Inside herdr it is only hidden while the highlighted
agent has nothing to open, which is the ask. Reporting it as a consequence of the
choice, not as a bug.

## Method

* `git show c329b0c -- switchboard/board.py switchboard/richboard.py`, then read
  `Reports`, `hint_lines`, `locate`, `files_for`, `_mtime`, `_inspect`,
  `last_assistant_texts`, `report_files`, and both `layout`s in the working tree.
* `python -m pytest tests/test_board.py` — 137 passed.
* Fork counting, the race, and the layout sweeps were run as throwaway scripts against
  the working tree (`locate`/`files_for`/`_mtime` stubbed); they are not committed.
* Not checked: the `oo` open handler, path extraction, `_editor`, anything from
  earlier rounds.
