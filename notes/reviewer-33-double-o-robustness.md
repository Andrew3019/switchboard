# Double-`o` — robustness & the redraw loop (commit 6da8dc8)

Lens: does the keypress handler hang or crash the curses board, or misbehave under bad
I/O? Path-extraction correctness, debounce semantics and injection are out of scope here.

**Verdict: needs changes.** Two proven crash paths escape `open_report_files`, which
documents itself as "never raises" and is called with no `try` around it in the event
loop — either one takes the whole board down. The freeze budget is real but bounded and,
I think, acceptable; the missing piece there is that nothing on screen says the board is
busy and nothing on the keyboard can stop it.

Baseline: `python -m pytest tests/test_board.py -q` → 115 passed.

---

## 1. (crash) A non-executable or non-runnable `editor.command` kills the board

`open_report_files` (board.py:1821-1826) catches exactly `FileNotFoundError` and
`subprocess.TimeoutExpired` around the editor calls. Every other `OSError` from the exec
escapes.

Trigger — any of:
- `[editor] command` pointing at a file without the execute bit (a wrapper script the
  user forgot to `chmod +x`);
- it pointing at a directory, e.g. `command = "/Applications/Cursor.app"`;
- a transient fork failure (`OSError` EAGAIN/ENOMEM) under load.

Proven:

```
$ python probe2.py
<tmp>/cursor        -> RAISED PermissionError (OSError) [Errno 13] Permission denied
<tmp>               -> RAISED PermissionError (OSError) [Errno 13] Permission denied
nosuchbinary-xyz    -> RAISED FileNotFoundError [Errno 2]        # this one IS caught
```

and end to end through the real function, with `_EDITOR` set to a mode-644 script and
`_inspect` stubbed to a valid detail:

```
open_report_files RAISED: PermissionError [Errno 13] Permission denied: '<tmp>/cursor'
```

Effect: the exception propagates out of the `if "o" in ev["raw"]` branch (board.py:2138)
— the loop's only handler is `except KeyboardInterrupt` — through `finally: restore()`,
so the terminal is restored but `main()` dies with a traceback and the agent loses its
board pane. The failure is permanent for that user, not transient: the same key kills
the board again on every restart until the setting is fixed.

Fix: catch `OSError` rather than `FileNotFoundError` at 1824, keeping the
`FileNotFoundError` message as the common case.

## 2. (crash) A transcript record whose `message` is not a dict kills the board

board.py:1860: `content = (rec.get("message") or {}).get("content")`. Every other field
in that loop is `isinstance`-guarded (`rec`, `content`, each `part`, `part["text"]`);
this one is not. Any truthy non-dict `message` raises `AttributeError`.

Proven, on files written to disk and read through the real function:

```
{"type":"assistant","message":"hello"}                       -> AttributeError 'str' object has no attribute 'get'
{"type":"assistant","message":[{"type":"text","text":"hi"}]} -> AttributeError 'list' object has no attribute 'get'
```

and through `open_report_files` with a stubbed `_inspect`:

```
open_report_files RAISED: AttributeError 'str' object has no attribute 'get'
```

Effect: identical to finding 1 — board down. `last_assistant_texts` reads an untrusted
file that switchboard does not write, so the guard is worth having for the same reason
the other three are. Realism is the honest caveat: Claude Code's own JSONL always has an
object here, so this needs a transcript in some other or corrupted shape. It is one
`isinstance` and it is the only unguarded field in the function.

Fix: `msg = rec.get("message"); content = msg.get("content") if isinstance(msg, dict) else None`.

## 3. (freeze, no crash) Up to ~80s of dead board, un-interruptible and unannounced

The handler is fully synchronous in the single-threaded select loop: one `sb inspect`,
then one `cursor <folder>`, then one `cursor -r -g <file>` per file, up to
`MAX_OPEN_FILES = 6` — eight subprocesses, each with `timeouts.subprocess = 10`.

- Upper bound if every call runs just under its timeout: ~80s frozen.
- A call that actually times out ends the loop (the `except` is outside the `for`), so a
  hung editor costs 10s once, not 10s × N. That part is fine.
- `sb inspect` measured at 0.23s here (`time ./bin/sb inspect reviewer-33 --json -n 1
  --events 1`), so the normal cost is the editor spawns, not the store read.

What is wrong is what happens during the freeze:
- **No feedback.** `msg` is assigned only from the return value, so the board never draws
  "opening…". The user sees a dead pane and no reason for it.
- **No way out.** `tty.setraw` clears `ISIG` (verified in the stdlib source), so ctrl-C
  during the freeze is just a byte waiting in the tty buffer, not a signal. The SIGINT
  handler installed at board.py:2076 cannot fire from this keyboard. Nothing the user can
  type stops it; only an external SIGTERM does.
- SIGWINCH during the freeze sets `dirty[0]` but cannot redraw, so a resize mid-freeze
  leaves a garbled pane for the duration.

Not a crash, and mostly invisible when cursor is warm. Worth either drawing a status line
before shelling out, or a shorter timeout for this one action.

Adjacent (belongs to the debounce round, noted only for the interaction): leaning on `o`
re-fires once per read batch. The freeze buffers more `o`s, the next read carries them as
one run, `double_press_run` fires again, and the freezes chain. Firing "at most once per
run" bounds a single run, not successive ones.

## Non-findings — probed and clean

- **Huge transcripts.** `deque(fh, maxlen=400)` reads the file from byte 0, but a real
  16MB transcript tails in 0.024s and a 7MB one in 0.008s. Not a freeze contributor.
- **`sb inspect` failure modes.** Nonzero exit, `sb` absent from PATH and not executable
  in this build, `OSError`/`SubprocessError` from the spawn, non-JSON stdout, and JSON
  that is not an object are all caught in `_inspect` (board.py:1878-1897) → `None` →
  "could not read this agent". No escape found.
- **Missing `cwd`/`transcript`.** Both come from the DB as str-or-None
  (status.py:2467-2469), so `Path(...)` cannot get a wrong type. Absent `cwd` returns a
  status line; absent `transcript` yields no files and still opens the worktree.
- **Bad transcript I/O.** Missing file, a directory in place of the file, 4KB of random
  bytes, torn/garbage JSONL lines, `{"type":"assistant","message":{"content":[{"type":
  "text"}]}}` with no `text` key — all return `[]` cleanly. `errors="replace"` covers
  invalid UTF-8; the `OSError` catch covers the rest.
- **`~` with no HOME.** `Path("~/x.md").expanduser()` falls back to the passwd database
  and does not raise, so the un-caught `RuntimeError` I expected there does not exist.
- **Editor launcher holding the pipes.** `subprocess.run(capture_output=True)` waits for
  EOF on the pipes, not for process exit, so a launcher that returns immediately while
  leaving a background child on the inherited fds burns the full 10s per call — I
  reproduced that with a shim (`sleep 30 & exit 0` → TimeoutExpired after 10.0s). It does
  *not* apply to the configured `cursor`: /usr/local/bin/cursor runs VS Code's cli.js,
  which detaches the app. Inferred from reading the shim — I did not launch cursor. A
  different `editor.command` (an `open -W` wrapper, a `--wait` alias) would hit it, and
  the message then says "timed out" for an editor that worked, with the remaining files
  never opened.

## Test coverage

`tests/test_board.py` covers `last_assistant_texts` for the missing-file case only
(line 1744). There is no test anywhere for `open_report_files`' error handling, which is
why both crash paths are unpinned. Two tests would pin them: `_EDITOR` set to a
non-executable file, and a transcript line with a string `message`.
