# Pane-lag hypothesis: does `sb cleanup` routinely leave a dead parent over live children?

Task: test the hypothesis that `cleanup`'s live-descendants gate reads *state*, not pane
presence, so a parent gets closed over `done`-but-uncleaned children — and that this makes
the symptom common rather than rare. READ-ONLY on the live store; no code changed; the only
file written is this one.

**Verdict in one line: the mechanism is real and I reproduced it, but the frequency claim is
refuted. Measured the way the task asked (pane closes, not `ended_at`), it happened once in
7.9 days.**

---

## 1. The mechanism — confirmed, and already named in the code

`Broker.live_descendants` (`switchboard/broker.py:4336`) ends:

```python
return [a["name"] for a in self._descendants(name)
        if a["state"] in store.LIVE_STATES and not a["ended_at"]]
```

State only. A child that has called `sb done` is not in `LIVE_STATES`, so it does not hold
the gate — regardless of whether its pane is still open. The gate itself is
`broker.py:3904-3914` (computed up front for every candidate) and `broker.py:4046-4052` (the
`held` refusal in the loop).

The asymmetry is not accidental: the neighbouring `pane_holding_descendants`
(`broker.py:4376`) exists precisely for it, and its docstring says so —

> "A descendant that has reported `done` and not yet been closed is dead to the first and
> alive to the second, and that gap is the whole of the disagreement an operator sees when
> `sb cleanup` says `already closed` about a row `sb status` lists."

It is used at `broker.py:4037-4045` only to *explain* an `already closed` refusal. It gates
nothing.

There is also an existing test for exactly this shape:
`tests/test_broker.py:2322 test_already_closed_names_the_descendant_still_holding_a_pane`,
whose docstring cites issue #53. So this is known behaviour, not an undiscovered hole.

**Live proof I ran** (throwaway script in scratchpad, `FakeHerdrAPI`, temp store — nothing
committed):

```
before cleanup: {'lead1': ('done', 'w1:lead'), 'kid1': ('done', 'w1:kid')}
live_descendants(lead1) = []
pane_holding_descendants(lead1) = ['kid1']
cleanup(['lead1']) closed: ['lead1'] refused: []
herdr panes closed: ['w1:lead']
after cleanup: {'lead1': ('done', None), 'kid1': ('done', 'w1:kid')}
```

The parent's pane is closed; the child's is not. Combined with `AgentStatus.archived`
(`status.py:609-638`, `alive is False and age >= SPAWN_GRACE`), that is exactly the board
symptom. **Hypothesis step 1: upheld.**

---

## 2. What the events log can and cannot answer

Before the counts, the fidelity limits — they bound everything below.

**Recorded pane closes:**
- `cleanup` (436 events) — switchboard deliberately closed the pane. Exact timestamp.
- `cleanup_pane_gone` (1) — the pane was already absent when cleanup ran.
- `gone` (89) — the reap path *observing* an absence, debounced by
  `timeouts.gone_confirm_grace = 60.0s` (`defaults/settings.toml:270`), so it lags the real
  pane death by up to a minute.

**Not recorded at all, and this is the load-bearing gap:** a pane that dies while the row is
already `done`. `status._record_gone` (`status.py:1068+`) only ever writes for rows in
`REAPABLE`; a `done` row is not reapable, so nothing is written and `pane_id` is never
cleared. Proof: `board-teardown` is `state=done`, `pane_id='w1B:pM'`, no `gone`, no
`cleanup` — and herdr does not list it (checked live). Its own log shows
`ring_failed [agent_not_found] agent target board-teardown not found` **five seconds after
its `done`**, so the pane was gone from that moment and the store still says otherwise
today.

Consequences I had to work around:
- **`pane_id` is not evidence of a live pane.** My first pass treated `pane_id`-set children
  as "still open" and produced three fake incidents of 27h, 105h and 155h. All three
  evaporate once herdr is asked. Discarded.
- **Historical liveness cannot be reconstructed.** The `herdr` event kind (18,263 events)
  does log every `agent list` call — 6,313 of them — but `out` is truncated at 500
  characters, i.e. one or two agents. It is not a usable liveness history. I did not invent
  a proxy for it.

So the honest scope: **I can measure incidents where both the parent's and the descendant's
pane ends are recorded. I cannot see any incident whose parent pane died while `done`.**

---

## 3. The measurement

465 agent rows, 55 parents, `created_at` span ≈ 7.9 days — the whole store.

**How each parent's pane ended:**

| | count |
|---|---|
| `cleanup` (deliberate close) | 31 |
| `gone` (crash / reap / closed from outside) | 17 |
| **unrecorded — blind spot** | **7** |

The 7 blind-spot parents are `board-fix` (14 children), `github-issues` (14), `main-11` (10),
`main-16` (11), `issues` (4), `dead-parent-rows` (3), `board-teardown` (1). `github-issues`,
`issues` and `dead-parent-rows` are alive right now, so they are not incidents. The other
four are `done` rows whose panes have gone with no record — any incident under those is
invisible to this method, and they are the widest fan-outs in the store. **This is the one
place Andrew's "under-counted" worry could still be right, and I cannot close it.**

**Ordering, for the 32 parents where both ends are recorded** (parent close vs. the latest
recorded descendant close):

| ordering | count |
|---|---|
| descendants closed ≥1h before the parent | 8 |
| descendants closed <1h before | 15 |
| descendants closed <1m before | 6 |
| **descendant closed AFTER the parent** | **3** |

**The 3, individually:**

- **`fix-options-2` (+79m) — false positive.** Cleaned up at 1786257945, then `restore`d
  242s later, and `revise-design*` were only delegated at 1786262359 — after the restore.
  Its real pane end is a `gone` at 1786271829, *after* every child. Not an incident.
- **`plugin-redesign` (+7 to +9s) — same command.** Parent and four children closed inside
  one 9-second cleanup batch, parent first. Real per the mechanism, invisible in practice.
- **`suggestions-plugin` (+3.5h) — the real one, and it is exactly Andrew's shape.** Child
  `worker-46` reported `done` at 1786814629; the parent was cleaned at 1786814864 (235s
  later) while `worker-46`'s pane was still open; `worker-46`'s pane was finally closed by a
  `cleanup --force` at 1786827627. A 3.5-hour window with a closed parent over a
  pane-holding child.

**Two independent cross-checks, both landing on the same single case:**

1. *Descendant showing signs of life after the parent's pane end* (own events, or a
   successful herdr call naming it): 2 parents — `suggestions-plugin`/`worker-46` (+3.5h)
   and `main-2`/`scout-cleanup` (+6m).
2. *`cleanup_refused` with reason `already closed`* — the operator hitting the
   store-says-closed / board-still-draws-it disagreement: 173 such refusals; only **3** of
   them fired at a moment when a descendant's pane was still open, and all 3 are
   `suggestions-plugin`. (Note: the payload records the bare reason; the newer
   "still drawn on the board because these below it still hold a pane" wording is in the
   code I read but is not in these historical payloads, so it cannot be counted from them —
   it will be countable going forward.)

Separately, the crash path produced one long incident that has nothing to do with cleanup
ordering: **`main-10` reaped (`gone`) at 1786734258, child `worker-9` still going until
1786807713 — 20.4 hours.** That is route A1, not this hypothesis.

**Window distribution of genuine cleanup-ordering incidents:** 9s, 3.5h. n=2.

---

## 4. Does the earlier "rare" conclusion survive?

**Yes.** `scout-dead-parent-evidence.md` said 3 of 53 by an `ended_at` proxy. Measuring pane
closes instead — the measurement the task asked for, and the one that is supposed to reveal
the hidden cases — gives **1 real cleanup-ordering incident, plus 1 nine-second one, plus 1
crash-path incident**. The count does not grow. The earlier scout also already identified
`suggestions-plugin` as pending-cleanup lag on an already-finished child, which is precisely
this mechanism, correctly diagnosed.

Where the earlier scout was wrong is the *reason*: it wrote that the invariant "holds by
construction, always" and that `cleanup` could not do this. It can, and §1 shows it doing it.
Rarity is not coming from the gate.

**Where it does come from — the answer to task step 4, and it surprised me.** I expected
"the sweep takes the whole subtree in one command". It does not: of 184 parent/child pairs
that both have cleanup events, only **11** were closed in the same batch (batch = cleanup
events <15s apart; 278 batches, 194 of them a single agent). Children are cleaned up in
*separate, earlier* commands — 23 of 32 parents had every descendant closed more than a
minute before, 8 of them more than an hour before. The intended leaves-up order is what
people actually do, one command at a time, and that is why the window rarely opens.

So: the mechanism is a loaded gun that is genuinely almost never fired, because the parent is
normally the last thing anyone cleans up.

---

## 5. Smallest change that would shrink the window (not implemented)

In order of size, smallest first:

1. **Log it.** When `cleanup` closes a candidate whose `pane_holding_descendants` is
   non-empty, write an event (the data already exists at that point — the call is right
   there at `broker.py:4038` for the *refusal* path). Costs nothing, changes no behaviour,
   and makes this countable instead of archaeological. Given the numbers above, knowing is
   worth more than preventing.
2. **Warn the operator at the moment of the close**, in the same sentence the refusal path
   already uses: "closed `X` — `worker-46` below it still holds a pane and will keep the row
   on the board." One line, no gate.
3. **Do not turn the gate into a pane-presence gate.** `live_descendants`'s docstring gives
   the reason it is store-only, and the same argument applies here: a `done` child whose
   pane is stale-open would then block the parent's cleanup forever, and the cost is a
   refusal the human has to fight. The `--force` leaves-up cascade already landing on
   `integrate-force-cleanup` is the better lever, and I would not duplicate it.

---

## 6. What I did not test

- The 4 dead blind-spot parents (`board-fix`, `main-11`, `main-16`, `board-teardown`). Their
  panes died with no record, so incidents beneath them are unmeasurable by any method the
  store supports. They hold 36 children between them. If the true count is higher than 1,
  it is hiding here.
- Whether `gone`'s 60s debounce hides short windows — a parent reaped and a child closed
  within that minute would read as simultaneous. Only affects sub-minute windows.
- I ran no live multi-agent repro in an isolated clone; the mechanism proof in §1 is the
  broker driven directly against a temp store with the test suite's `FakeHerdrAPI`, and the
  board rendering is inferred from `AgentStatus.archived`'s definition, not observed.
- I did not run the test suite — nothing changed, so there was nothing to regress.
