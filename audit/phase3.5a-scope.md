# Phase 3.5a scope — `sb tell --needs-reply`

Read-only pass first, then the build. Base: `main` at `5998a43`, branch
`phase3.5a-needs-reply`. Scope is BUILD-PLAN.md's 3.5a row only — the flag, the store
state behind it, and the text the recipient actually reads. Not the reconciler (3.5), not
the delivery modes (3.1), not the `[sb: from <name>]` tagging (3.3).

Ground truth: `DESIGN-TRUTH.md:230-234` — "There is `tell` only. No agent ever waits on
another agent. `tell --needs-reply` inserts a static prompt saying you must reply to that
agent at some point, since it is waiting for a reply."

## What existed before this branch

`grep -rn 'needs.reply\|needs_reply'` over the tree found nothing outside prose
(`BUILD-PLAN.md`, `audit/phase3-scope.md`). The flag, the column and the prompt text were
all unbuilt, exactly as `audit/phase3-scope.md:186-191` reported.

The full path a `tell` travels, verified against the code at that commit:

1. **Parsed** — `cli.py:155-158`. `sb tell` takes `who`, `message`, and a hidden `--re`.
2. **Validated** — `cli.py:392-394` (`validate.targets`, `validate.text`).
3. **Dispatched** — `cli.py:784` → `Broker.tell`.
4. **Persisted** — `Broker.tell` (`broker.py:3196-3239`) → `store.put_message`
   (`store.py:1257-1280`), writing a row of the `messages` table (`store.py:190-214`).
5. **Announced** — `self._ring(t, self._say("notify.mail"), ...)` (`broker.py:3238`). The
   doorbell carries no payload by design; it says "You have mail. Run: sb inbox"
   (`defaults/prompts.toml:65`).
6. **Read** — `Broker.inbox` (`broker.py:3344-3355`) → `store.unread_for`
   (`store.py:1282-1298`), rendered at `cli.py:853` as `[id] from X: body`.

So there are exactly two moments the recipient reads text: the doorbell (step 5) and the
`sb inbox` output (step 6). **Step 6 is the one that carries the message itself, and it is
where the static prompt belongs** — the doorbell deliberately carries no payload, and its
four `[notify]` strings are the files item 3.3 is scoped to rewrite.

## Pass/fail tests, written before the change

1. `sb tell w "..." --needs-reply` parses and the flag reaches the store: the message row
   has `needs_reply=1`. **Fail** = no flag, or the flag parsed and dropped.
2. The recipient's `sb inbox` output for that message contains the static prompt telling
   it to reply to the sender at some point because the sender is waiting. A plain `tell`'s
   inbox output does not. **Fail** = the flag is stored but the recipient never reads
   anything different, which is the whole feature.
3. Nobody waits. `sb tell --needs-reply` returns on the same path a plain `tell` does — no
   polling loop, no block, no wait for an answer, and the sender's exit is unchanged.
   **Fail** = any new wait, which contradicts DESIGN-TRUTH's "no agent ever waits on
   another agent".

## What was touched, and why

- `switchboard/store.py` — `messages.needs_reply` column (default 0, which is what every
  pre-existing row means: an ordinary tell); `put_message(..., needs_reply=False)`. The
  store's own schema-deficit migration (`store.py:406-427`) applies the ALTER, so no
  hand-written migration. A column rather than text glued into `body`: the body must stay
  what the sender actually typed (`sb inspect` and `sb log` show it), and 3.5's reconciler
  needs a queryable flag to find an unanswered one.
- `switchboard/cli.py` — `--needs-reply` on the `tell` parser; passed through at dispatch;
  the inbox render appends the prompt for flagged messages.
- `switchboard/broker.py` — `Broker.tell(..., needs_reply=False)`, passed to
  `put_message`. Nothing else in `tell` changes; no new ring, no new wait.
- `defaults/prompts.toml` — one new `[notify]` key, `needs_reply`.

## Shared files, declared

`cli.py`, `broker.py` and `defaults/prompts.toml` are all files items 3.1/3.2/3.3 will
also touch. Kept as small as possible to make the merge mechanical: `broker.tell` gains
one keyword argument and one pass-through line; the `tell` parser gains one
`add_argument`; the inbox render gains a suffix line rather than a rewrite of `cli.py:853`
(the exact line 3.3 is scoped to change); the prompt is a new key, not an edit to any of
the four `[notify]` strings 3.3 rewrites.

## Live proof (run against an isolated clone, then torn down)

`git clone` of the repo into a scratch directory, `git checkout phase3.5a-needs-reply`,
driven by that clone's own `./bin/sb` from inside it. `sb doctor` confirmed its own store
(`<clone>/.git/agentflow/state.db`), `sb status` confirmed it empty.

Agent-to-agent, which is the in-spec path (`DESIGN-TRUTH.md:246-249`: `sb tell` is for
agents only, both ways round). A real agent `nr35a-sender` ran
`sb tell nr35a-proof "Which branch are you on?" --needs-reply`; a real agent
`nr35a-proof` was rung, ran `sb inbox`, and read, verbatim:

```
[3] from nr35a-sender: Which branch are you on?
    [reply needed] nr35a-sender is waiting for a reply to this. Nobody is blocked on it
    and it does not interrupt what you are doing — but answer it at some point, with
    `sb tell nr35a-sender "..."`, before you finish.
```

It then replied with `sb tell nr35a-sender "..."` — message 4 in that store — so the round
trip closed on the delivered text alone. Test 1 passed (`needs_reply=1` on the row), test 2
passed (a plain `tell` sent to the same agent in the same mailbox carried no such line),
test 3 passed (the sender's `tell` returned at once and went on to its own `sb done`;
nothing blocked, and no reply was waited for). Both agents cleaned up with
`sb cleanup --force`, the clone deleted, `herdr workspace list` clean afterwards.

## One edge found, deliberately not fixed here

A **human-sent** `--needs-reply` renders `answer it with sb tell human "..."`, and
`Broker.tell` refuses a message to the human (it has no mailbox). Observed live on the
first run: the agent tried it, was refused, and folded its answer into `sb done` instead —
a wasted step, not a lost answer. Not fixed, because `sb tell` is agent-only in both
directions by `DESIGN-TRUTH.md:246-249`, so a human using this flag is already outside the
design, and the fix is either a second prompt string (which item 3.3 would then also have
to rewrite) or a refusal at send time — both bigger than this item. Reported rather than
taken on.
