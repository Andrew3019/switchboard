# Probe findings: lsof cwd gate (Q1) and herdr restart behavior (Q2)

Both questions from "What remains open or unproven" in `design/fix-options.md`
(items 1 and 2) were settled by running real commands on this machine, not by
reasoning. No repo file was modified. No production `sb`/herdr process was
touched — Q2 used a fully isolated throwaway herdr server (own socket/config/
state dirs under `/tmp`), the same pattern the design doc used for its tab-
teardown experiment. Both throwaway environments were torn down after use;
nothing was left running.

## Q2 first, because it contradicts the design doc's framing

**The design doc undersells this. It isn't that herdr's restart behavior is
merely untested — the mechanism that would make `agent list` distinguishable
after a restart doesn't exist at all.** I read the handler, not just a
docstring.

`herdr agent list` → `Method::AgentList` → `handle_agent_list`
(`src/app/api/agents.rs:16-23` in `/Users/andrew/Code/herdr`) →
`self.collect_agent_infos()` (`src/app/agents.rs:21-35`), which iterates
`self.state.workspaces` — pure in-memory state, no persistence layer
consulted, no error path. `encode_success` is called unconditionally. There
is no failure branch: `agent list` **cannot return an error or a "partial"
signal**, by construction. It always returns `{"agents": [...]}` with
whatever `self.state.workspaces` currently holds.

I verified this live, not just by reading:

1. Started an isolated herdr server (`herdr server`, XDG dirs under
   `/tmp/herdr-restart-probe.*`), created a workspace/pane, and used
   `herdr pane report-agent` to mark it as a working agent (`--source
   probeswitchboard --agent probeagent --state working`).
2. `herdr agent list` returned the agent:
   `{"agents":[{"agent":"probeagent","agent_status":"working",...,"workspace_id":"w1",...}]}`
3. `kill -9` the server pid directly (simulating a crash, not `herdr server
   stop` — the graceful path wasn't tested and is a different case).
4. Started a fresh `herdr server` against the same config/state dirs.
5. Immediately, before doing anything else: `herdr agent list` →
   `{"agents":[],"type":"agent_list"}`. Exit 0. No error, no warning field,
   nothing to distinguish this from "the workspace has zero agents and
   always did."
6. `herdr workspace list` in the same moment *did* show the workspace
   (`w1`, `pane_count: 1`, restored from the on-disk session snapshot) — so
   the workspace itself survives the restart, but the agent report attached
   to its pane does not. **And the restored workspace was handed the exact
   same `workspace_id` ("w1") it had before the kill** — not merely "an id
   that no longer means anything," but a *reused* id that could silently
   collide with bookkeeping keyed on it. Confirms the id-instability comment
   at `broker.py:1226-1229` (`_tab_for`'s docstring: "ids are handed out per
   herdr run"), but the doc's own worry undersells the failure mode — reuse,
   not just staleness.

**Answer:** right after a restart, listing agents returns an **empty
success**, unconditionally, every time. It is never a partial answer and
never an error at the `agent list` layer. I also checked whether any other
call exposes a restart signal a caller could check first — `herdr status
server` (no uptime/pid/start-time field, just `status/version/protocol/
socket`) and `herdr api snapshot` (no timestamp field either) — neither
carries anything usable. **A caller cannot tell "herdr has been up for days
and this workspace really has zero agents" apart from "herdr restarted 200ms
ago and forgot everything" by calling `agent list`, or anything else herdr
exposes, at all.** This is exactly the scenario F6/Wave 4's gate worries
about, confirmed by direct observation rather than inferred from a
docstring — and it's *more* load-bearing than the design doc states, because
there is no degraded-but-detectable middle state to catch: it is
indistinguishable by construction, not just untested.

**Consequence for the builder:** the live-cwd (`lsof`) observation in Q1
below is not a corroborator for the restart case — it is the *only* signal
that can catch it, exactly as F6 says. Nothing herdr itself exposes can. Any
implementation that treats an empty `agent list` result as evidence of "still
up and genuinely empty" is wrong; only a failed/refused herdr call (down
entirely) or the lsof-based check can be trusted for that distinction, and
they answer different questions ("is herdr up" vs "did herdr forget").
Confirming this required launching a throwaway herdr instance and killing it,
which needed explicit judgment about whether that was safe — it was, because
it never touched the live production socket other agents in this workspace
depend on. If a future builder wants to re-run or extend this experiment,
reuse the same isolated-XDG-dir pattern (see `scripts/
smoke_live_handoff_sessions.sh` in `/Users/andrew/Code/herdr` for the
reference pattern); never point it at `$HOME/.config/herdr`.

I did not test the graceful `herdr server stop` → restart path (only a hard
`kill -9`), and I did not test what happens to a genuinely still-running
*agent process* (e.g. a live `claude` subprocess) whose pane is restored —
only the ephemeral hook-reported state. Both are worth a follow-up if the
builder needs finer-grained confidence, but neither changes the answer above:
`agent list`'s success is unconditional regardless of which restart path
produced the empty state.

## Q1 — does the lsof-based live-cwd check work on macOS

Settled, cleanly, with real output on this machine (not a VM, not a
container — the machine building Wave 4 will run on).

### Recommended invocation

```
lsof -a -d cwd -F pcn
```

- `-d cwd` selects only the "current working directory" file-descriptor type
  per process (not open files, not `+D` — `+D <path>` is a different,
  expensive recursive-open-files-under-a-directory scan and is the wrong
  tool here; it answers "what has this directory's contents open," not
  "whose cwd is this directory").
- `-a` ANDs the selection criteria (harmless/no-op with only one criterion
  given, but keep it — it's what stops a second criterion silently turning
  into OR if one gets added later, e.g. `-u`).
- **Do not pass `-p <pid>`** to scope to the caller's own process tree for
  exclusion purposes — do the exclusion in the parser (by pid), not by lsof
  filtering, so a single invocation answers the whole-machine question once.
  Scoping with `-p` on a nonexistent/wrong pid list returns exit 1 with
  empty output (verified: `lsof -a -d cwd -p 999999 -F pcn` → exit 1, no
  stdout) — that shape is indistinguishable from a real failure, so don't
  build a code path that could produce it.
- `-F pcn` is the machine-parsable field-output mode: PID, command name,
  and file **n**ame — the three fields needed. No `-F` (or `-F` with other
  letters) is more fragile since the human-readable format's column widths
  and header line are not designed for parsing.

### Real sample output on this machine

```
p339
cPowerChime
fcwd
n/
...
p73823
csleep
fcwd
n/private/tmp/lsof-deleted-test-dir
```

Structure, confirmed over 328 processes with zero exceptions: strict
repeating groups of exactly 4 lines, `p<pid>`, `c<command>`, `f<fd-type>`
(always literally `fcwd` here, since `-d cwd` was the only fd type
requested), `n<absolute-path>`. Every `n` line began with `/`. No
permission-denied markers, no truncated groups, no stray lines. Parser rule:
split on lines starting with `p`, treat each block's `n` line as that
process's cwd; a block that doesn't have exactly one `c`/`f`/`n` line
following its `p` line is unparsable output and must be treated as a failure
(mandatory refusal), not skipped.

### Cost

Three consecutive runs, unfiltered (full-machine scan, 328 processes):
0.23s, 0.07s, 0.06s wall-clock. No `sudo`, no elevated privileges — ran as
the normal login user, clean exit 0, empty stderr on all three runs. This is
cheap enough to run on every `sb workspace close` invocation, including the
mandatory re-confirm step 3 in the design's ordering.

### Deleted directory

Tested directly: started `sleep 60` with cwd set to a temp directory, then
removed that directory out from under the running process
(`rmdir`/`rm -rf` while the process still had it open as cwd — this works on
macOS/POSIX, no error). `lsof -a -d cwd -p <pid> -F pcn` still reported
`n/private/tmp/lsof-deleted-test-dir` — the same path string, no
`(deleted)` suffix or any other marker (unlike Linux `/proc`, which does
mark deleted-but-open paths). **This is actually the safe direction for the
gate**: a process whose cwd directory has already been removed still shows
up under the original path string, so a component-wise "does this path sit
under the checkout path" comparison still catches it and the gate still
refuses correctly. There is no macOS-specific case here where a live process
goes invisible to this check because its directory was deleted.

### Failure modes

- **Missing binary**: tested by pointing `PATH` away from `lsof`'s
  location. Via a shell (`env PATH=... lsof ...`) this is a shell-level
  "command not found," exit 127. **The shape that matters for the builder is
  different**: Python's `subprocess.run` with an argv list (no shell) raises
  `FileNotFoundError`, not a `CompletedProcess` with a nonzero return code —
  the mandatory-refusal code path must catch that exception explicitly, not
  just check `returncode != 0`, or a missing `lsof` will crash instead of
  refusing.
- **Non-zero exit**: reproduced two ways — invalid flags (`lsof -bogus`
  exits 1, usage text to stderr) and a `-p` filter matching nothing (exits 1
  with empty stdout, as above). Both are real, reachable exit-1 shapes;
  treat any non-zero exit as a failure requiring refusal, don't try to
  special-case "exit 1 might just mean no matches" — with the recommended
  unfiltered invocation, "no matches" is a parsing-time answer (an empty or
  all-non-matching result set from a *successful*, exit-0 parse), never an
  exit-code question.
- **Timeout**: not exercised against a genuine hang (nothing on this machine
  made lsof hang), but the invocation is cheap (see Cost above) and a
  generous timeout (a few seconds) wrapped around the subprocess call is
  standard practice — timeout expiry must be treated identically to
  non-zero exit, i.e. mandatory refusal, not a retry-and-hope loop.
- **Truncated/unparseable output**: not observed in practice on this
  machine (output was clean over 328 processes across every run), but the
  parser rule above (strict p/c/f/n grouping, refuse on anything else)
  covers it structurally rather than by having reproduced a real truncation.

### Can a parser distinguish "no processes" from "I could not tell"?

**Yes, and cleanly, but only if the invocation is the unfiltered whole-machine
scan described above, with strict parsing.** "No processes under this path"
is: exit 0, output parses cleanly into complete p/c/f/n blocks (possibly
zero blocks, possibly many), and zero of the parsed cwd paths are
component-wise under the checkout path. "I could not tell" is: exit
nonzero, the binary is missing, the process times out, or the output fails
the strict block-structure check above. These are structurally disjoint —
there is no output shape that is ambiguous between them, *given* the parser
refuses on anything that doesn't match the exact expected structure rather
than trying to be lenient. A lenient parser (e.g. one that best-effort
extracts `n` lines regardless of surrounding structure) would reintroduce
the ambiguity the design's refuse-on-failure rule depends on not existing;
don't build one.

### Component-wise path comparison — confirmed genuinely needed, not
hypothetical

`git worktree list` on this machine, right now:

```
/Users/andrew/.herdr/worktrees/switchboard/fix-options      f1193d0 [fix-options]
/Users/andrew/.herdr/worktrees/switchboard/fix-options-2    0a38fd4 [fix-options-2]
```

`"/Users/andrew/.herdr/worktrees/switchboard/fix-options-2/anything".startswith("/Users/andrew/.herdr/worktrees/switchboard/fix-options")`
is `True` in Python — a plain `str.startswith` gate on `fix-options` would
treat every process working inside the unrelated `fix-options-2` worktree as
"under" `fix-options`, and `sb workspace close fix-options` would refuse (or
worse, in a differently-shaped bug, wrongly succeed) based on a sibling
workspace's live processes. This is real on this machine today, not a
contrived example — confirmed directly from `git worktree list`, not
inferred. Component-wise comparison (split both paths on `/`, compare
directory components as a list, e.g. `pathlib.Path(...).parts` prefix check
or `os.path.commonpath`) is required, exactly as the design says.

## What's settled and what isn't

**Settled, with direct evidence, both questions:**
- Q1: the exact `lsof` invocation, its real output shape, its cost, its
  deleted-directory behavior, its failure shapes, and the sibling-worktree
  nesting risk — all run for real on this machine.
- Q2: herdr's `agent list` behavior immediately after a restart — read from
  source (`collect_agent_infos`, unconditional success) and confirmed live
  against a throwaway isolated herdr instance.

**Not settled, flagged for the builder rather than silently dropped:**
- The graceful `herdr server stop` → restart path was not tested, only a
  hard `kill -9`. I'd expect the same result (still no error path in
  `handle_agent_list`) but didn't verify it directly.
- Whether a genuinely still-alive agent *process* (not just the hook-report
  metadata) survives being restored into a new herdr generation, and
  whether `lsof`'s cwd observation would still see it correctly in that
  case, wasn't tested — only the ephemeral report state was. This doesn't
  change either answer above, since the lsof check is process-tree-based
  and independent of herdr's own bookkeeping, but a builder relying on both
  signals together (as Wave 4 does) may want it confirmed.
- lsof permission behavior was only observed for the current user's own
  processes on this single-user dev machine; TCC/Full Disk Access
  restrictions on a different macOS configuration weren't exercised (none
  showed up here — no permission-denied processes at all in the 328-process
  scan).

Nothing here contradicts `design/fix-options.md`'s own framing, except that
Q2's answer is more absolute than the doc allows for: it isn't that herdr's
restart behavior is unread, it's that the code path that would need to
distinguish "restarted" from "genuinely empty" does not exist to be read —
`agent list` has no failure mode at all. Worth restating loudly to whoever
builds Stage 6b: the lsof-based check is not a second opinion that
corroborates herdr's answer, it is the *only* opinion that can be right
about this specific case.
