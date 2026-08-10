# AUDIT 2C — findings: inbox, message prefix, the herdr channel

Auditor: `audit-2c-inbox`. Read-only; no code or docs changed.

**Tree audited:** `/Users/andrew/.herdr/worktrees/switchboard/worker-2` @ `a9dd319`.
**Tree the `sb` on PATH runs:** `/Users/andrew/Code/switchboard` @ `caa6d20` (main), via
`/Users/andrew/.local/bin/sb` → `/Users/andrew/Code/switchboard/bin/sb`, which inserts that
repo root on `sys.path`.
**Do they differ?** No. `git diff --stat caa6d20 HEAD -- switchboard/ bin/ defaults/` is
empty, and the main checkout is clean. So every live run below exercises exactly the code
quoted below, and local `main` fixes none of the gaps.

Verdicts: **0 SATISFIED, 2 PARTIAL, 1 BROKEN.**

---

## Entry 1 — `sb inbox --peek` stays, and once read a message is never brought up again

> "**`sb inbox --peek` stays, and it must be clear that once a message is read it will not
> be brought up again.**" — DESIGN-TRUTH.md:252

### Verdict: PARTIAL

The mechanism is right in every part. The *clarity* half of the entry — "it must be clear"
— is not delivered anywhere an agent will see it.

**`--peek` exists and does not consume** — `switchboard/cli.py:154-156`

```
ib = cmd("inbox", help="read your unread messages")
ib.add_argument("--peek", action="store_true",
                help="do not mark as read (safe for polling)")
```

→ `switchboard/cli.py:774` `msgs = b.inbox(me=me, peek=args.peek)`
→ `switchboard/broker.py:2816-2826` `return store.unread_for(self.db, me or self.whoami(), mark=not peek)`
→ `switchboard/store.py:1271-1286`: rows are selected on `read_at IS NULL`, and `read_at`
is only written `if rows and mark`. So `--peek` leaves `read_at` NULL. Confirmed live:
`sb inbox --help` prints both flags; `sb inbox --peek` and `sb inbox --peek --json` returned
`(no new messages)` / `{"messages": []}`.

**A normal `sb inbox` marks read, and read messages are never re-shown or re-delivered**

- Re-shown: `store.unread_for` (store.py:1278) filters `read_at IS NULL`, so a read row can
  never come back out of `sb inbox`.
- Re-delivered: the doorbell sweep is `Broker.flush_pending` (broker.py:3337), which reads
  `store.unseen(...)` — and `unseen` (store.py:1311-1326 → `_pending`, store.py:1329-1341) is
  `delivered_at IS NULL AND read_at IS NULL`. A read row is excluded forever. store.py:1314-1324
  documents this as the exact reason `unseen` exists rather than `undelivered`.
- Verified live against the store (`/Users/andrew/Code/switchboard/.git/agentflow/state.db`):
  my own message row is `{'id': 357, 'to_agent': 'audit-2c-inbox', 'read_at': 1786317955,
  'delivered_at': 1786317949}` after one `sb inbox`, and a subsequent `sb inbox --peek`
  returned nothing.

**Where it falls short — nothing tells the agent this.** The protocol prompt every agent
gets says only (`defaults/protocol.md:99`):

```
`sb inbox` reads your unread messages — run it whenever you are told you have mail.
```

That is the entire treatment. It does not say reading consumes, it does not say a read
message will never be raised again, and it never mentions `--peek` at all — so the flag the
entry protects is invisible to the only population that can use it. The `sb inbox` output
itself (cli.py:778, `[{id}] from {sender}: {body}`) adds no such note either.

### Gaps (entry 1)

- `defaults/protocol.md:99` does not state that `sb inbox` consumes: a read message is never
  shown or announced again.
- `defaults/protocol.md` never mentions `sb inbox --peek`, so no agent knows a non-consuming
  read exists.
- `sb inbox`'s own output (`switchboard/cli.py:778-780`) prints messages with no line saying
  they are now read and will not reappear.
- `--peek`'s help text says "do not mark as read (safe for polling)" but not the converse —
  that a plain `sb inbox` is one-shot (`switchboard/cli.py:155-156`).
- Side effect worth a task: a peeked message that was already rung has `delivered_at` set and
  `read_at` NULL, so `unseen` will never ring for it again (store.py:1336-1337) while
  `cleanup`'s unread gate still counts it — a peek-only agent can pin itself open.

---

## Entry 2 — every sb message is prefixed so it is clearly an sb message

> "**Every sb message is prefixed so it is clearly an sb message**, and the prefix can carry
> more — the sender agent's name and the like. The channel is the same as Andrew typing; the
> prefix is what tells them apart." — DESIGN-TRUTH.md:90-92

### Verdict: BROKEN

Nothing sb puts on the wire into a Claude chat box carries an sb marker or a sender name.
The prefixing that does exist is in the wrong place: inside `sb inbox`'s *tool output*, which
is not the channel the entry is about.

**The wire has no prefix.** Every message into the chat box goes through `Broker._ring`
(broker.py:3386) → `self.h.prompt(who, text)` (broker.py:3431) → `herdr.py:471`
`self._call("agent", "prompt", name, text)`. `text` is passed through untouched at all three
levels — there is no prefixing step anywhere on the path.

The four texts that travel it, from `defaults/prompts.toml`:

| line | text as sent |
|---|---|
| `prompts.toml:63` | `mail = "You have mail. Run: sb inbox"` |
| `prompts.toml:71` | `mail_question = "You have mail (a question) — someone is waiting…"` |
| `prompts.toml:81` | `child_done = "A child finished. Run: sb inbox. …"` |
| `prompts.toml:93` | `interrupt = "[INTERRUPT — stop now] …"` |

Only `interrupt` carries a bracketed prefix, and it announces *urgency*, not sb-origin and
not a sender. The other three are bare sentences indistinguishable from something Andrew
typed.

**Spawn task delivery is the same** — `switchboard/broker.py:2646` `self.h.prompt(name, task)`
sends a child's first task raw, unprefixed and unattributed.

**Live proof, from this very session.** My first turn arrived as the task line and the
doorbell concatenated with no separator and no marker:

```
Read /tmp/sb-audit-2c-inbox.md and carry out exactly what it says.You have mail. Run: sb inbox
```

Nothing there says "sb", nothing says who sent it.

**What prefixing does exist, and why it does not count.** `switchboard/cli.py:778` renders
inbox rows as `[{id}] from {from_agent}: {body}` — which is how I saw
`[357] from audit-2b: …`. That is a *tool result* inside a turn the agent already chose to
spend, not the channel Andrew shares. Likewise `vocabulary.done_prefix = "[done] "`
(`defaults/settings.toml`, used at `switchboard/status.py:183,690-691`) is explicitly an
internal marker that readers **strip** — settings.toml calls it "an implementation detail of
the mailbox rather than something everyone must know". Neither satisfies the entry.

### Gaps (entry 2)

- `Broker._ring` (`switchboard/broker.py:3386-3438`) applies no prefix before
  `self.h.prompt(who, text)` — add one central prefixing point there so nothing can bypass it.
- `defaults/prompts.toml:63,71,81` (`notify.mail`, `notify.mail_question`, `notify.child_done`)
  carry no sb marker; they read exactly like a human-typed line.
- No sender name reaches the chat box on any path — the entry's "the prefix can carry more —
  the sender agent's name" has no implementation at all.
- `switchboard/broker.py:2646` delivers a spawned child's first task unprefixed and
  unattributed, so an agent cannot tell its task from a human's typing either.
- `notify.interrupt`'s `[INTERRUPT — stop now]` (`defaults/prompts.toml:93`) is the only
  bracketed marker and it is not an sb marker — if a scheme is chosen it should subsume this
  rather than sit beside it.

---

## Entry 3 — how herdr actually talks to Claude

> "**How herdr actually talks to Claude.** It types into the chat box and presses enter… If
> Andrew is halfway through typing when a message is sent, the half-written text goes along
> with it, because sb pastes and hits enter. While Claude is working, a message is queued by
> Claude's own system and delivered on the next turn. Interrupt is pressing escape on the
> chat window, which interrupts the model, and then the message goes in directly without
> waiting." — DESIGN-TRUTH.md:82-88

### Verdict: PARTIAL — the interrupt half is exactly right; the queueing half is contradicted
by the code, and the paste-and-enter half is not sb's code to evidence.

**(a) Types into the chat box / paste-and-enter — UNVERIFIED at source, corroborated live.**
sb never types anything itself on this path: it shells out to `herdr agent prompt <name>
<text>` (`switchboard/herdr.py:471`), and the typing happens inside the herdr binary, which
is not in this repo. `herdr agent prompt --help` documents it only as "Submit a prompt to an
agent". The nearest in-repo corroboration is the *pane* path, `Herdr.prompt_pane`
(`herdr.py:473-489`), whose comment records the measured behaviour — "`pane run` types but
does not reliably submit into a TUI prompt box, so the explicit `enter` is required" — and
which does `pane run` then `pane send-keys <pane> enter`. The half-typed-text claim is
directly corroborated by this session: audit-2b reported my task "was left sitting unsent in
your prompt box", and it arrived fused to the doorbell with no separator (quoted under entry
2). That is paste-and-enter behaviour observed, not proven from source.

**(b) "While Claude is working, a message is queued… delivered on the next turn" —
CONTRADICTED by the code, in comments *and* in design.** `Herdr.prompt`
(`switchboard/herdr.py:457-470`):

```
**This INTERLEAVES. It does not queue.** An earlier note here said the opposite… Re-verified
against a genuine 60-second multi-step turn: the poke was handled at +13s while the running
task did not complete until +63s.
```

The same claim is load-bearing in the broker, not incidental: `broker.py:11-15` ("a prompt
INTERLEAVES rather than queues"), `Broker._ring` (`broker.py:3389-3392`), and the actual
guard `if not force and self._busy(who): … return False` (`broker.py:3426-3428`) which
*defers every doorbell while the target is mid-turn*. `store.undelivered`
(`store.py:1292-1295`) repeats it. So the whole deferral machine exists **because** the code
believes the opposite of this sentence. One of the two is wrong; per this repo's rules
DESIGN-TRUTH wins and the code contradicts it, which is a decision for Andrew, not for me.

**(c) Interrupt is escape, then the message goes in directly — SATISFIED.**
`Broker.interrupt` (`switchboard/broker.py:3184-3226`):

```
3216:  self.h.send_keys(name, "esc")
3217:  time.sleep(INTERRUPT_SETTLE)   # let the cancel land before the new one
3220:  body = self._say("notify.interrupt", text=text)
3224:  self._ring(name, body, force=True)
```

`send_keys` → `herdr agent send-keys <name> esc` (`herdr.py:491-499`); `herdr agent send-keys
--help` confirms "Use esc as the canonical Escape key name". `force=True` is what bypasses
the busy-defer in `_ring` (`broker.py:3426`), so the text does go in directly without
waiting, and the payload travels **inline** here rather than as a bare doorbell — matching
"the message goes in directly".

### Gaps (entry 3)

- `switchboard/herdr.py:460-468` asserts `agent prompt` INTERLEAVES and does not queue,
  directly contradicting DESIGN-TRUTH.md:85-86 — needs Andrew to say which is true before
  anything is built on either.
- The entire busy-defer path (`Broker._ring`, `switchboard/broker.py:3426-3428`, plus
  `flush_pending` at 3348-3351) is built on the interleaves belief; if the truth entry stands,
  deferring while working is unnecessary machinery and messages are being delayed for nothing.
- `store.undelivered` / `unseen` docstrings (`switchboard/store.py:1292-1295, 1311-1324`)
  restate the interleaves claim, so a correction has three files to land in, not one.
- The paste-and-enter mechanism is unevidenced in this repo — it lives in the herdr binary.
  If it matters it should be pinned by a test or a recorded observation, not left to a
  comment on a different code path (`herdr.py:485-489`).

### Adjacent, out of my scope — reported, not fixed

- `sb interrupt` is a top-level verb (`sb --help`, `switchboard/cli.py`), while
  DESIGN-TRUTH.md:287 rules out "`sb interrupt` as a verb" and DESIGN-TRUTH.md:216-227 makes
  interrupt a delivery *mode* of `tell`. `sb tell` currently has no mode flags at all
  (`switchboard/cli.py:148-151`). Belongs to whoever owns the delivery-modes entry.
- `sb ask` still exists (`sb --help`, `broker.py:2713`) against DESIGN-TRUTH.md:283.

---

## Process notes

- My task was not delivered on spawn — it sat unsent in my prompt box and only went in when
  audit-2b's follow-up message pushed it through. That mis-delivery is itself evidence for
  entries 2 and 3 and is quoted above.
- Nothing was committed: the task is read-only and the report lives at
  `/tmp/sb-audit-2c-inbox.md`, outside the repo, as instructed.
- No agents were spawned; every check was a non-mutating read (`sb --help`, `sb inbox --help`,
  `sb inbox --peek`, `herdr … --help`, a read-only SQLite query).
