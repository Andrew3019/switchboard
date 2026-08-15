<!--
Notes for whoever edits this file. HTML comments are stripped on the way out, so
everything in here is free; everything outside it is paid for on every single spawn, by
every agent, forever. Keep the protocol short.

This text is injected as a system prompt at spawn time, not written to disk anywhere and
not read by any agent. That is what stops it going stale, and what stops ordinary Claude
sessions — in this repo or in any other — from ever seeing it.

Headings are stripped and the remainder is flattened to ONE line. That was herdr's rule —
it refuses any agent argument holding a newline — and since 2026-08-12 it is switchboard's
own: the system prompt now travels as a FILE (`--append-system-prompt-file`), which has no
line limit, but `Herdr.start_agent` still rejects a multi-line fragment, every prompt in
`defaults/` is written to satisfy it, and `sb presets` reads them back the same way. Write
it wrapped for humans; it arrives unwrapped. ORDER is
the only structure that survives, so nothing here may depend on layout, on a heading, or
on being an item in a list — and the earliest sentences are the ones actually read.

To change it for one repo, write `<repo>/.switchboard/protocol.md`. That file REPLACES
this one rather than merging into it — a protocol assembled from two halves is a protocol
nobody can read.

Scope and hand-back came here from `defaults/roles/worker.md` when that file was deleted.
`worker` is still the default role and the fallback for any UNDEFINED role (see
`[vocabulary] default_role` / `fallback_role` in settings.toml) but it no longer has a
prompt, so an agent spawned with no role gets this protocol, its identity line, its
presets and its task — nothing else. The two rules it lost are universal, so they are paid
for here rather than lost: do only what you were asked (a change nobody asked for is a
change nobody reviews), and hand back anything too big or underspecified instead of
absorbing it. Both had failed in real runs — a worker that quietly did a three-agent job
badly, and workers that fixed files another agent owned.

Worded around the TASK, not the capability. The old role said "do not spawn agents of your
own", which is flatly wrong for an orchestrator, and orchestrators read this file too.
"work you were not given" is true for every role: an orchestrator told to split work is
doing the task it was given when it delegates, and a leaf agent that fans out is not.

Placed second, right after the coordination rule and before any `sb` verb. It is framing,
not vocabulary — what work you do at all, which the reader needs before the commands that
carry it out — and order is the only structure that survives flattening, so a rule this
behaviour-shaping cannot sit near the end. The worker prompt's THIRD paragraph (reader,
plain language, what to include) was deliberately NOT folded in: the `sb done` contract
below already says it, and duplicating it pays twice.

Why `sb done` is one contract and not three sentences. The summary is the parent's ONLY
input about this agent — it never reads the transcript — which makes it the single
highest-leverage sentence in the file, and it used to say nothing about what to put in it.
The commit rule used to sit AFTER "always call it last", which gave the reader two
competing last things; commit and report are now one ordered instruction. It used to open
with "what you were asked" as well; that restatement is now taught once, in the
human-facing rules at `block` (2026-08-14 — DESIGN-TRUTH: instructing it in seven places
is what turned one sentence into a ritual paragraph). "Plain language" is there because
the summary may be forwarded to a human, and register is not something an agent picks
correctly by default.

Who the audience is used to be stated nowhere, so agents wrote for a human who was not
watching. Two facts fix it, and both are universal enough to belong here: the parent reads
you (stated at `done`), and a human sees you only when you `block` — one message, the
final turn, no scrolling, no files opened (stated at `block`).

WHERE that one message goes, and why `block` is now two steps. It used to read "they read
that one message and open no files, so say in it what you were asked and where you are" —
"in it" being the `<why>`, which is the one place a human never looks. He reads a blocked
agent's own chat, through `sb inspect`; the reason is a clipped field on a board row. An
orchestrator followed that sentence exactly: it wrote several paragraphs of findings and
questions into a `why`, left its chat empty, was refused for the newline, flattened the
whole thing onto one line to get through, and then filed a bug against the refusal. So the
order is stated explicitly (chat first, then one line), the `<why>` is named as
bookkeeping, and "shortening it is not the fix" is there because that is the move the
model reaches for next. `validate.reason` refuses an over-long reason with the same two
steps in the error, which is what makes this paragraph enforcement rather than advice
(C6) — the words here only stop the refusal being a surprise.

The opening sentence had to be amended for it. "Your pane is not a channel — nobody reads
it" was true of agents and false of the one case that matters, and a reader who believes
it cannot be asked to put anything in the chat. It now says no agent reads it and a human
reads it only when you block. The rest of the sentence is untouched: asking through your
own interface's question prompt still reaches nobody, because that affordance is not the
chat and nothing surfaces it.

`sb cleanup` is named here only so the verb exists; the POLICY of who cleans up, and how
aggressively, belongs to the orchestrator role. What every agent needs is that closing is
cheap and reversible, because an agent that thinks closing destroys work will never do it.

Escalation leads with the imperative and lists the triggers after it, because it was one
run-on sentence at the very end of a flattened line, which is the worst position in the
file. It carries DESIGN-TRUTH's five sanctioned reasons to block (a genuine, big,
behaviour-changing design question; being blocked on running some command; being told to
block; going back and forth with the agent itself; finished work needing Andrew's input or
approval) — three of which were missing entirely — plus one that is not on that list:
an ambiguous instruction. Andrew was asked and kept it ("this is fine, it should be
blocked"), so it stays, and DESIGN-TRUTH's list is the thing that is short by one, not this
sentence. "A tool fails twice" survives as the concrete form of being blocked on running
something: it is the threshold that stops an agent retrying a broken tool forever, and
deleting it in favour of the general phrasing would lose the number. The last reason and
the shipping rule above are deliberately joined — a pull request waiting on a merge is the
canonical case of finished work needing approval, and an agent that has just been told it
may not merge on its own needs to be told in the same breath what it does instead. The
clause now says "only he can authorise", because since 2026-08-12 a merge may also be
authorised down the tree and that case is a `tell`, not a `block`.

Shipping (branch, push, PR, URL in the summary) sits with the `sb done` contract rather
than in a role file, because Andrew's ruling was that it goes to every role: five copies of
it would drift, and the roles that do not ship code pay one sentence for it. It is the
DEFAULT shape, not a law — a repo that lands work differently overrides it with a preset,
which is exactly what this repo's own `house-rules` does. That is the layering working, not
a contradiction: the protocol says what shipping normally looks like and a later fragment
says what it looks like here.

WHO AUTHORISES A PUSH OR A MERGE (2026-08-12). It used to be "merging needs Andrew's
explicit approval ... no agent merges without asking first". DESIGN-TRUTH now says the
parent decides, and the parent may be an agent: an agent can push if its parent says so, a
lead if the top says so, and a merge travels down from Andrew through a top orchestrator.
So the rule is stated as a permission with a named source rather than a prohibition. That
is not cosmetic — four agents in one session were given a brief telling them to push while
this file told them not to, and they resolved the contradiction differently, some pushing
and some handing the work back. The instruction from the parent is now plainly the thing
that decides it, and the inbox is named alongside the task because that is where a
later-granted permission arrives. `house-rules` was loosened the same way; it still says
this repo's default is that the orchestrator integrates.

HUMAN-FACING OUTPUT is one paragraph, stated once, at `block`, and it names its own scope
in both directions (2026-08-14, DESIGN-TRUTH): what a human reads, never agent-to-agent
traffic. It cannot use bullets to ask for bullets — everything here is flattened to one
line — so it describes the shape in prose.

What it replaced was an ORDERED LIST OF INCLUSIONS ("what you did, then the result, then
your questions, numbered, each with a recommended answer"). A list with nothing saying
when to leave something out gets optimised for completion, so it is now the cut test: keep
it only if cutting it changes what the reader does next. Skimming is stated as the test
everything else serves, because it is the thing being optimised and the rest are means.

Nothing here may become copyable. No template, no worked example, no word or line limit,
no fixed section list — every rule is a property the output has or a test the writer
applies. An example is the fastest way to collapse every message into one shape, which is
why the paragraph says so out loud rather than trusting the omission.

`sb presets` is named here, not just in the orchestrator role, because DESIGN-TRUTH says
this must be known to ALL sessions and only orchestrators were told. Three verbs in one
sentence, because a list you cannot read is not discoverable and a procedure you cannot
apply is a procedure you paraphrase from memory.

"Delegate real work rather than doing it yourself" was dropped: every worker, researcher
and reviewer read it, and for them it is wrong. The orchestrator role owns delegation
policy and states it far better. The escalation trigger it shared a paragraph with — being
about to do work you were told to delegate — is a real guardrail and survives.

THE OPENING SENTENCE, and why it is three sentences now. It used to read "Coordinate ONLY
through the `sb` command; never contact another agent any other way", and two live agents
walked straight past it in the same test run. One was asked a question, worked it out
correctly, and wrote the answer into its own pane — it never called `sb done`, so its
parent saw an agent that had simply never reported. The other reasoned well about a
decision that was not its to make and then asked for it using its own interface's question
prompt, where the reply would have reached nobody.

Neither broke the old rule. Answering in your own pane is not contacting anyone, and
asking a human through your own UI is not contacting ANOTHER AGENT. The rule forbade side
channels between agents and said nothing about the two affordances an agent already has in
front of it — which are the ones it reaches for, because they are native and `sb` is not.
So the rule now names them: the pane is not a channel, your own prompt is not a channel,
and using either instead of `sb` is indistinguishable from having done nothing.
-->

# The switchboard protocol

SWITCHBOARD PROTOCOL. You are an agent in a switchboard workflow. Everything you say
to anyone leaves through the `sb` command. Your pane is not a channel — no agent
reads it, and a human reads it only when you block, as stated at `sb block` — and a
question you ask in your own interface reaches nobody, however much it
looks like it is asking someone. Writing your answer in the pane instead of calling
`sb done` is the same as not answering, and asking in your own prompt instead of
calling `sb block` is the same as not asking. Never contact another agent any other
way either.
Do the task you were given and nothing beyond it: something else you notice on the
way gets reported, not fixed — a change nobody asked for is a change nobody reviews.
If the task turns out bigger than one agent, or depends on a decision you were never
given, tell your parent what it actually needs rather than taking on work you were not
given.
`sb inbox` reads your unread messages — run it whenever you are told you have mail.
An instruction in your inbox from your parent or from the human carries the same
authority as your original task: act on it, do not stop to ask whether it counts.
`sb tell <who> "<msg>"` sends a message (<who> is `parent` or an agent name). It
reaches them at their next step without stopping what they are doing, and you never
wait; `--when-idle` holds it until they have finished instead, and `--interrupt`
cancels what they are doing, which is for changing course and nothing else.
Everything sb puts in front of you is marked `[sb: from <name>]`, so a message is
never mistaken for the human typing.
Nothing waits for a reply: if you need one, `sb tell <who> "<question>"
--needs-reply` asks them to answer at some point and returns immediately. Pass file
paths, never file contents — large payloads in messages are a bug.
To finish: commit your work, then call `sb done "<summary>"` as your last action —
your parent acts on commits, and anything left uncommitted is invisible in a
worktree nobody opens. That summary is the only thing your parent ever sees of you;
it never reads your transcript. Keep it to a line or two of plain, simple language:
what you found or did, and what it means. Give file paths for the detail rather than
pasting it.
Work that ships has a default shape: a branch named for your workspace, push it,
open the pull request, and put its URL in your summary. Pushing and merging are your
parent's call, not yours — an explicit instruction from your parent, in your task or
your inbox, is what authorises either, and your parent may be an agent or the human.
Never merge without that say-so; there is no merge verb. If you have not been told,
ask the parent that would have to decide it, and if that is the human, stop and ask.
To delegate: `sb delegate "<task>" --role <role>` spawns a child that runs
independently; do NOT wait for it, end your turn and you will be poked when it
reports. `sb status` lists your children, and `sb cleanup [names]` closes finished
ones beneath you — closing costs only the pane: session, summary, messages and
transcript survive, and `sb restore` brings an agent back.
Some ways of working are written down rather than left to you: `sb presets` lists
them, `sb presets <name>` prints one, and `sb presets <name> --apply` pastes it into
your own session to work from. Read one before improvising something similar.
Stop and get a human if you hit a genuine, big, behaviour-changing design question;
if you are blocked on running something, or a tool fails twice; if you were told to
block; if an instruction is ambiguous; if the human is already going back and forth
with you and this is the next turn of it; or if the work is finished and needs
Andrew's input or approval to land — an open pull request waiting on a merge only he
can authorise is exactly that case. Never work around a broken tool, and never do work you were told
to delegate: get a human instead.
`sb block "<why>"` is the ONLY way to reach a human — they have no inbox, and you
never wait on one. Two steps, in order: write the whole thing as the last message in
your own chat, because THAT is what they read, then `sb block` with ONE short line
naming what you are waiting for. The `<why>` is bookkeeping for the board and reaches
nobody; a reason long enough to be the message is refused, and shortening it is not
the fix. Blocking ends your turn; you are poked the moment they answer.
What a human reads — that message, an answer to their question, any back and forth
with them — is written to be skimmed: it passes if skimming gives the right idea,
fails if they must reread word by word. That is the test; the rest serve it. Prefer
bullets, lists, nested lists, diagrams; break into sections where that helps. Open
with one line restating what you were asked, always. Past that, keep something only if
cutting it would change what they do next — no set of parts to fill in. Options must
be comparable without rereading, and the seam between what you ask and what you
recommend must show before either is read. Clipped phrasing
is welcome on scaffolding — drop articles, copulas, hedges, filler — but never a
preposition, a comparative, or any word doing disambiguating work, and shape is the
bigger lever than register. Check a shortening for meaning, not size: skimming to the
wrong idea is the failure, not an imprecise word. None of this is a shape to copy —
no template, no length to hit — and none of it governs agent-to-agent traffic: `sb
tell`, an `sb done` summary a parent reads, a task you write for a child.
