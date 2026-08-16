# Positioning research notes — subagents/agent-teams vs switchboard, and orchestration frameworks

Task: /private/tmp/claude-501/-Users-andrew-Code-switchboard/2475cfa7-549f-4d2a-adcb-64d167470f52/scratchpad/task-positioning-research.md
Draft written to: /Users/andrew/Code/switchboard/.positioning-draft.md (untracked, not gitignored — left untracked per instructions, not committed)

## (a) Claude Code subagents vs agent teams — verified against official docs

- Plain subagents (https://code.claude.com/docs/en/sub-agents): own context window, custom
  system prompt/tools, spawned when the lead's task matches a subagent description, "the
  lead agent seeing only each subagent's final summary, never its intermediate steps." No
  mid-run addressability by a human is described for plain subagents; they exist for the
  duration of the delegating call.

- Agent teams (https://code.claude.com/docs/en/agent-teams) — a DISTINCT, newer, still
  experimental feature (env var CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1; doc describes
  behavior "as of v2.1.178"). This is the important correction to the rejected draft:
  - Teammates ARE addressable: each has a name, and "any teammate can message any other by
    that name." A human can message any teammate directly too ("Unlike subagents ... you can
    also interact with individual teammates directly without going through the lead"), via
    the in-process agent panel (arrow keys + Enter) or by clicking into a split tmux/iTerm2
    pane.
  - Messaging mid-run IS possible: peer-to-peer via a mailbox (`~/.claude/teams/{team}/
    inboxes/{agent}.json`), delivered automatically; humans can also type into a running
    teammate's pane directly.
  - They persist beyond a single turn — a teammate keeps running/idling across many turns
    until explicitly shut down, notifies the lead when idle, and split-pane mode literally
    puts one teammate per tmux/iTerm2 pane, which is architecturally close to what
    switchboard does with herdr.
  - Where it still differs from switchboard (all confirmed from the same doc):
    - No nested teams / no tree: "teammates cannot spawn their own teammates. Only the lead
      can manage the team." One team per session, lead is fixed for the session's lifetime.
    - No persistence past the process: team config dir is deleted when the session ends; "no
      session resumption with in-process teammates" — /resume does not restore them.
    - No worktree-per-agent built in: the docs list git worktrees as a *separate*, manual
      alternative approach ("Manual parallel sessions: Git worktrees ... without automated
      team coordination"), not something agent teams set up for you. Avoiding file conflicts
      is left to the user ("Break the work so each teammate owns a different set of files") —
      same soft convention switchboard leans on for a lead's shared worktree, not something
      Anthropic's version does better or worse, just not automated either way.
    - No separate human channel: there's no board, no block/delivery-mode distinction — you
      just type into whichever pane is active. Permission prompts for all teammates bubble
      up into the lead's session specifically, which is its own design, not a general human
      channel.

## (b) Orchestration frameworks — verified via search summaries + one direct fetch

- LangGraph, CrewAI, AutoGen/AG2, OpenAI Agents SDK: per multiple 2026 comparison articles
  (not primary docs — treat with slightly less confidence than the Claude Code docs above),
  these all run agents as in-process graph nodes / role objects / conversational loops that
  make model API calls inside your own process. None of them are described as driving real
  terminal sessions of an actual coding agent (e.g. Claude Code) against a real repo — they
  are frameworks for building custom agent applications, not for orchestrating existing
  coding-agent CLI sessions. Topology: LangGraph and CrewAI are declared up front (a graph /
  a crew config); AutoGen's conversation loop is comparatively more dynamic but still
  in-process. Did not find a primary-source claim from any of the four of driving real
  terminal coding-agent sessions or handling multi-agent edits to one repo via worktrees.

- dmux (https://github.com/formkit/dmux) — fetched and read directly. Confirmed: it creates
  one tmux pane and one git worktree per task, launching real coding-agent sessions (Claude
  Code, Codex, Cline, etc.) — genuinely the closest architectural analog to switchboard's
  pane-per-agent-over-real-sessions shape found in this research. But confirmed no
  agent-to-agent messaging, no completion-report protocol, no delegation tree in its
  documentation — it's flat parallel isolation with manual merge, not a coordination
  protocol. Other similarly-named tools turned up in search (Tmux-Orchestrator,
  claude-tmux-orchestration) were NOT independently verified — only search snippets were
  seen for those, not primary docs, so no claims about them went into the positioning draft.

## Bottom line for "does anything occupy switchboard's niche"

Nothing verified does the whole thing: a tree of orchestrators (not just one flat team),
one messaging verb with delivery modes, and a single dedicated human channel, driving real
per-pane coding-agent sessions. Agent teams is the closest *native* Claude Code answer to
"can a human reach an agent mid-run" and "can agents message each other," which the
rejected draft got wrong by omission; dmux is the closest pane/worktree-per-agent tool but
has no coordination layer at all.

## v2 revision (rewrite for length + grounding in PRINCIPLES.md/DESIGN-TRUTH.md + gastown)

Andrew rejected the first draft (347 words) as too long and as a feature comparison
instead of a principles-grounded one. Follow-up brief:
/private/tmp/claude-501/-Users-andrew-Code-switchboard/2475cfa7-549f-4d2a-adcb-64d167470f52/scratchpad/task-positioning-v2.md

New draft: /Users/andrew/Code/switchboard/.positioning-draft.md — 160 words total across
both comparisons (target was ~150; over by 10, kept because cutting further meant dropping
either the agent-teams correction or the gastown death date, both of which Andrew explicitly
asked to see verified).

### What gastown is (verified from this repo's own prior primary-sourced research —
did not re-fetch, treated as already verified since it's dated and cites primary sources)

Read in full: `research/07-gastown-github.md` (repo/code investigation) and
`research/08-gastown-sentiment.md` (community sentiment, dated 2026-08-06). Gastown ("Gas
Town") is Steve Yegge's open-source multi-agent orchestrator (Go, MIT, 17,482 stars):
a "Mayor" coordinates per-project "Rigs," dispatching ephemeral worker agents ("Polecats")
through a tmux+git-worktree layout, with a SQL-backed work ledger ("Beads") and a
Bors-style merge queue ("Refinery"). It is the closest thing in this research to
switchboard's ambition — many coding agents, one repo, a human gate — and DOES have a
real, enforced human-gate mechanism (an `interactive: true` step type that pauses a
workflow DAG for human input, confirmed in the Go source by report 07).

**But it is dead.** Steve Yegge declared it finished in a post dated 2026-08-03 (11 days
before this research, quoted directly in report 08): "Gas Town fell apart at the seams
with Opus 4.7 ... the Opus tic never went away, so Gas Town effectively burned down." He
has moved to a successor called Wheelhouse. Corroborating facts from the same report:
`main` frozen since 2026-07-23, last release 2026-06-06, zero commits in 2026-08,
57% of the open backlog untriaged, and the community's own dominant conclusion (echoed
by dozens of independently-surfaced HN/Reddit comments) is that its four-tier
agent-supervising-agent hierarchy (Mayor/Deacon/Witness/Refinery/Polecat) didn't hold —
agents violated their own protocol, "doctor" could never fully repair state, and idle
supervision alone burned ~132M cache-read tokens in 3 hours in one filed issue.
**This is not something I discovered fresh — it was already thoroughly researched and
verified by primary sources (Yegge's own posts, the GitHub repo/issue tracker) already
in this repo's `research/` directory before I started. I read it, did not re-derive it,
and did not re-verify it against live sources myself given the depth already there.**

### Does gastown overlap anything I claimed as distinguishing for switchboard?

Partially — and I said so plainly rather than hiding it. Gastown DID ship a real,
enforced human-gate mechanism (`interactive: true` steps), so "nobody ships a resumable
human gate" would have been an overclaim; report 07 itself concludes the narrower true
claim is "nobody ships a human gate that separates decision from data and reconciles it
back into the graph." I did not put a human-gate claim in the v2 draft at all, to stay
inside verified territory and inside the word budget. The draft's gastown paragraph
makes only two claims: (1) it died on 2026-08-03, both verified from report 08's primary
source quote, and (2) it ran agents-supervising-agents in-repo via a real terminal/worktree
setup unlike LangGraph/CrewAI/AutoGen, which is also directly supported by report 07.

### Which principles from PRINCIPLES.md / DESIGN-TRUTH.md the v2 draft is built on

- **C1 (tree topology, no sibling/mesh comms)** — reflected in the agent-teams paragraph's
  "teammates can't spawn teammates, so there's no tree" and the gastown paragraph's framing
  of "four-tier hierarchy of agents supervising agents" as the thing that didn't hold.
- **C6 (enforce mechanically, never instruct)** — reflected in "nothing forces a report
  before a turn ends" (agent teams expose a `TeammateIdle` hook but don't wire a default
  policy requiring one, unlike switchboard's default-installed Stop gate) and echoed by
  gastown's catalogued failure mode of *inferred* completion (no git diff ⇒ done) instead
  of *reported* completion.
- **C14 (the human is a node, not a spectator; the blocked-leaf shortcut)** — reflected in
  "reaching a teammate is just typing into whichever pane is focused, not a distinct signal
  a board can show" — the contrast is switchboard's board/`sb block`, which surfaces a
  blocked agent directly to the human UI without walking the tree.
- **Rejected:** C10 (idle costs nothing) and C15 (generality earned, not designed) both
  fit gastown well (its idle-token-burn numbers, and Yegge's own "I only ever wound up
  using it to build itself" quote) but there wasn't room in the ~150-word budget to use
  them without cutting a claim I'd already verified more directly. Left them out rather
  than compress them into something hedgy.
- Did not use C2/C3/C7/C8/C9/C11/C12/C13 — none of them map to a comparison point that
  survived verification against the other tools within the word budget.

## v3 revision (genre change — first-person honest answer, not a comparison)

Andrew rejected v2 too: not for length, but genre — he wanted the honest first-person
answer to "why did you build your own", grounded in the actual research/ survey he did,
not a scoreboard. Brief:
/private/tmp/claude-501/-Users-andrew-Code-switchboard/2475cfa7-549f-4d2a-adcb-64d167470f52/scratchpad/task-positioning-v3.md

New draft: /Users/andrew/Code/switchboard/.positioning-draft.md — 197 words (target
150-200), first person, no "unlike X" framing, nothing scored.

### The genuine reasons — found in research/, not reconstructed

Read `research/00-synthesis.md` in full (the cross-cutting synthesis of reports 01-06)
and `research/02-orchestrators.md` in full (the ~200-project landscape survey, and its
own executive summary + "Reconsider entirely" section at the end). Both are dated
2026-08-06/07, explicitly written *before a line of switchboard existed*
(`research/README.md` says so directly). This is the actual contemporaneous record the
draft is built on:

- **00-synthesis.md §1, "The headline: the original scope is mostly already built."**
  Quoting it directly: of the four differentiators the pre-build braindump assumed were
  novel, all four already shipped elsewhere — "Human→leaf direct addressing — ships in
  Claude Code Agent Teams, in nearly the same words. 13 of 13 tools examined preserve
  it." This is the source for the draft's first paragraph and its "most of what I thought
  I'd need to build turned out to already exist" line — I did not invent this humility,
  it's the literal first finding of his own research.
- **00-synthesis.md §2, "What is genuinely novel."** Verbatim: two things, "and they are
  the same thing viewed from two angles": (1) human-owned blocking steps that separate
  decision from data and reconcile — "Gas Town's `interactive = true` is a working
  durable gate... What remains true: nobody ships one that separates decision from data
  and reconciles it" (the crude `if step.Interactive || hasInteractive` freezing the
  whole workflow is described in `research/07-gastown-github.md` too, and is what the
  draft's "any interactive step... freezes the whole run" line is drawn from); (2)
  "Reconciliation semantics for out-of-band human intervention. When a human talks
  directly to a leaf agent, every supervisor's world-model goes stale... Nobody has
  solved this." This is the direct source for the draft's second paragraph and its
  entire reason-to-build.
- **00-synthesis.md, same section:** "Everything else in the braindump is table stakes
  we need in order to demonstrate these two. The controller is not the product. The
  human-gate + reconciliation layer is." — source for "I did not build another
  framework. I built those two things, thin."
- **02-orchestrators.md, "Reconsider entirely" (end of file):** explicitly told himself,
  before building, to "Set CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 and use it for a week...
  find out empirically which of the documented limitations actually hurt before building
  a system to fix them," and named the honest minimal-scope option: "the thinnest viable
  wedge is not another runner. It is a template/gate/reconciliation layer that sits on
  top of herdr... Everything else — panes, worktrees, adapters, kanban — is
  undifferentiated work that six projects will give you." This is the source for "on top
  of a terminal manager that already gave me panes and worktrees for free."

### What I found that contradicts how switchboard has been described so far

The research proposed a *bigger* thing than what actually shipped. 00-synthesis.md's
"Architecture that falls out of the research" section (§4) describes a broker daemon, a
declarative step-machine/template YAML with typed step types and `max_visits`-bounded
loops, and a learnings MCP server with labelled retrieval — none of which appear in
`DESIGN-TRUTH.md` or `README.md` as built. What actually shipped (per DESIGN-TRUTH.md,
already read in full in the first pass of this task) is narrower still: no templates, no
declarative workflow YAML, no learnings store — just the delegate/tell/done/block verbs,
the Stop-hook report enforcement, and the board. That's the source for the draft's last
line, "Everything else here ended up smaller than what I first sketched." I did not
overclaim this as a *problem* — it reads as switchboard having cut even further than its
own research recommended, toward the two genuinely-novel things and away from framework
scope, which is consistent with the whole thrust of both files rather than contradicting
it. I flagged it because the brief specifically asked what contradicts prior framing, and
this is the one real gap: earlier drafts and the README describe switchboard's finished
shape; the research directory describes a larger thing that was scoped down further once
building started.

I did not use "I started before agent teams existed" as a reason — checked, and it would
have been false. `research/02-orchestrators.md` already treats Claude Code Agent Teams as
a shipped, examinable feature (with its own row in the comparison table) in the same
research pass that preceded switchboard's build, so the honest reason is "I read Agent
Teams' own docs, including where they concede the mid-run-human-input gap, and built the
two things past that gap" — not "I didn't know it existed yet."

## v4 revision (shorter, lighter tone, and verify the closing-line correction)

Brief: /private/tmp/claude-501/-Users-andrew-Code-switchboard/2475cfa7-549f-4d2a-adcb-64d167470f52/scratchpad/task-positioning-v4.md
New draft: /Users/andrew/Code/switchboard/.positioning-draft.md — 111 words (target 90-120).
Dropped the "I did not skip the research" opening (read as defensive) and the closing
line about switchboard shipping smaller than its own research, per Andrew's correction
below. Kept the two genuine gaps and the "mostly it already existed" admission.

### Verification of the three claims Andrew disputed

**1. Learnings — did it ship as a plugin?** There is no plugin literally named
"learnings." `ls defaults/plugins/` shows exactly two: `report-bug` and `todo`. But the
*mechanism* research/00-synthesis.md asked for under "learnings" — "a small MCP server,
not a memory system... at step N, inject the rules for step N," durable structured state
via simple tooling instead of embeddings — is exactly what the general plugin
architecture is: `defaults/plugins.toml` documents a plugin as "a Python package that owns
a CLI verb and a directory of durable state," and `report-bug` (files structured bug
reports to durable state via `sb plugin report-bug file ...`) is a live instance of that
exact pattern. So Andrew's correction holds: the concept shipped, generalized into the
plugin system itself rather than a single-purpose "learnings" server. I did not put this
in the shortened draft (no room at 90-120 words) but it would have been the accurate
closing line if kept.

**2. Template YAML — does something of that shape exist?** Not a DAG-of-typed-steps with
gates (that never shipped — no workflow engine, no `.claude/workflows/*.js`-style step
machine, confirmed absent from both DESIGN-TRUTH.md and README.md). What does exist,
confirmed by reading `defaults/plugins.toml`, `defaults/presets.toml`, and the README's
own architecture section: all shipped behavior — roles, model tiers, the agent protocol,
presets like `adversarial.md`/`evidence.md`/`verify.md` — lives as layered TOML and
markdown data in `defaults/`, overridden per-repo by `.switchboard/`, "arrays joining
rather than replacing." That's the same "vocabulary is data, not code" spirit the
research's template proposal was reaching for, just applied to config/role/preset
composition rather than a multi-step workflow DAG. Andrew's "it exists in some form" is
fair; I did not claim it in the draft since it's not really the same shape as what
research meant by "template," and there wasn't room to explain the distinction at 110
words.

**3. Broker daemon — is it the board/collector?** Yes, confirmed directly from source.
`switchboard/broker.py` opens with the docstring `"""M3 — the broker.` and is exactly the
verb layer research called for. `switchboard/collector.py` is the one elected,
long-running, per-repo background process — it "collects the tree" on a timer, publishes
a snapshot, and "rings the doorbell... by SPAWNING sb" (delivering held messages). Between
`broker.py` (the verb contract) + `collector.py` (the one live background process) +
`store.py` (the SQLite state), that's the "broker daemon over SQLite" research/00-
synthesis.md's architecture section asked for — just split across three named modules
instead of one daemon binary, and without the graph-edge-permission model research
proposed (there's no per-edge routing table; the tree shape is enforced by spawn
mechanics instead, per `sb delegate`'s branching rules in DESIGN-TRUTH.md).

**Conclusion carried into the report:** all three exist, none of them missing — Andrew
was right and my earlier "smaller than I sketched" line was wrong. They shipped under
different names and a different physical split than the research proposed, not as gaps.
I cut the closing line from the draft rather than try to compress this nuance into the
90-120 word budget.

## v5 revision (register settled on D/A; research firstmate + AO; verify the subagent claim)

Brief: /private/tmp/claude-501/-Users-andrew-Code-switchboard/2475cfa7-549f-4d2a-adcb-64d167470f52/scratchpad/task-positioning-v5.md
New draft: /Users/andrew/Code/switchboard/.positioning-draft.md — 141 words (target
120-150). Register D/A (flat, factual, no first person).

### Firstmate and AO — what they are, and do they close either claimed gap?

Both were already covered in `research/02-orchestrators.md` (read in full in an earlier
pass of this task). I re-verified the load-bearing claims with fresh fetches/searches
today rather than relying on the seven-week-old research alone.

**Firstmate** (kunchenguid/firstmate, MIT, bash+markdown, ~3.0k★): a strict hierarchy —
Captain (human) -> Firstmate -> Crewmates, with optional Secondmates. Confirmed today via
WebSearch against the live GitHub docs: "the captain talks to the first mate and to
nobody else; every worker reports through the first mate and never addresses the captain
directly" — the sanctioned channel is Firstmate-mediated, not direct.

**But it has real, working answers to both of switchboard's claimed gaps, verified by
directly fetching `docs/architecture.md` today:**
- **Gap #1 (a human-owned gate that resumes cleanly):** Firstmate has a genuinely typed,
  mechanized resolution event. Quoted directly from the doc: "Crew status files are
  append-only wake-event logs, not current-state fields," "Decision-only events such as
  `resolved` never become current state or leak their prose into the current-state
  detail," and "`fm-send`'s `--resolve-key` appends the closing `resolved` line to this
  home's own copy" — written by the actor that answers, not the busy worker. That is a
  real typed decision-closure mechanism, not the "crude, any-interactive-step-freezes-
  everything" hack `research/07-gastown-github.md` found in Gas Town.
- **Gap #2 (reconciliation for out-of-band human intervention):** also has an answer.
  `research/02-orchestrators.md` quotes the docs directly: "Direct captain intervention in
  crewmate windows is treated as authoritative but reconciled at the next supervision
  review." Today's fetch of the same architecture doc corroborates from a different angle:
  "Explicit backend-target sends and direct human typing stay unmarked, so captain
  intervention in a secondmate pane remains conversational" — i.e. a human can type
  straight into a crewmate's window, and Firstmate has a stated (if periodic, not
  immediate) reconciliation story for it, not silence.

**Conclusion: Firstmate meaningfully narrows both claimed gaps.** Its answers are
convention/log-based (an append-only file plus a documented actor-authored marker) and
periodic ("next supervision review") rather than mechanically enforced or immediate —
switchboard's Stop hook refuses a turn to end without a report, and the board surfaces a
block the moment it happens rather than at the next scheduled review — but calling either
gap "nobody has a real answer" was too strong. I said so plainly in this report rather
than downplaying it. The honestly defensible narrower difference is mechanism
(hook-enforced and immediate vs. convention-based and periodic), not existence.

**AO** (AgentWrapper/agent-orchestrator, née ComposioHQ, Apache-2.0, Go+Electron, was
~8.8k★ in `research/02`, ~7,503★ per a June 2026 secondary source found today): flat
parallel workers plus one planner, no nesting, terminal-attach for direct human->leaf.
Fresh websearch today surfaced "task-level approval gates where decomposed plans require
human approval," "escalation directly to humans" after a timeout, and "human-on-the-loop
coordination with milestone gates" — **lower confidence than the Firstmate finding**,
since this came from aggregated secondary web sources, not a primary-doc fetch, and may be
describing a coarser plan-approval-before-execution step rather than a resumable,
per-decision gate. I did not find anything suggesting AO answers gap #2
(reconciliation for direct human intervention into a leaf agent) — `research/02` and
today's search agree AO's differentiator is its state-observation model (OBSERVE -> durable
facts -> DERIVE), not templates or gates, and neither source claims a reconciliation
mechanism for it.

### Honest answer: are there really only two gaps?

No — that framing was too strong, and I said so in the draft by dropping the "gap" framing
entirely rather than trying to defend a weakened version of it. Firstmate has working,
if less mechanized, answers to both. What survived scrutiny and is now in the draft
instead: a narrower, verified capability difference about **running a named procedure
across multiple simultaneously-live, independently addressable agents** — see below.

### The subagent claim — verified mechanically, and the Agent Teams case is genuinely harder

Read `defaults/presets/adversarial.md` in full (the actual procedure, not a description of
it). Its shape: ONE proposer agent is kept alive across every round, defending or revising
its own artifact; each round spawns a FRESH, independent reviewer agent given only the
artifact and a lens — explicitly "no earlier verdicts, no defence" — because its
independence is what lets it see what the proposer and prior reviewers have stopped
noticing; the orchestrator running the loop is a third, distinct role, judging convergence
against a hard round cap rather than being the artifact's own author.

**Against plain Claude Code subagents, the claim holds, and the reason is structural, not
a matter of discipline:** a subagent (Task-tool) call is a single request/response with no
resumable identity — once it returns, "the lead agent seeing only each subagent's final
summary, never its intermediate steps," it is gone (verified from
`code.claude.com/docs/en/sub-agents`, fetched in an earlier pass of this task). That means
a plain-subagent session has exactly ONE context that can persist across turns — the
parent — and any number of disposable ones. There is no way to keep a proposer alive as an
identity distinct from the orchestrator judging it while also spawning fresh, disposable
reviewers around it; the only persistent thing is the single session itself, which would
have to be both defender and judge. The adversarial-review procedure specifically requires
three simultaneously-distinct roles (kept-alive proposer, disposable reviewer, judging
orchestrator), and plain subagents give you room for only one persistent role.

**Against Agent Teams, the claim does NOT hold as an absolute impossibility, and I said so
rather than overclaiming.** Verified against `code.claude.com/docs/en/agent-teams`
(fetched in full in an earlier pass): teammates DO have persistent, independently
addressable identities that outlive a single turn, and any teammate can message any other
by name. In principle a lead could spawn one persistent "proposer" teammate and a fresh
"reviewer" teammate each round, relay the artifact and lens, then shut the reviewer down
and repeat — nothing in the documented limitations (no nested teams, one team per session,
lead is fixed) rules this out; only the lead can spawn teammates, but the lead can play the
orchestrator role here. What Agent Teams still lacks for this specific case, confirmed
from the same doc: no template/procedure file a human can name and reuse — the docs
describe spawning teammates from a natural-language prompt each time ("describe the task
and the teammates you want in natural language"), so the choreography (kept-alive
proposer, fresh uncontaminated reviewer, rotating lens, convergence rule, round cap) would
need to be re-explained by hand in the spawn prompt every time, rather than invoked as
`sb presets adversarial` reads a single written-down procedure file. That is the honestly
narrower claim now in the draft: not "impossible with Agent Teams," but "not written down
and reusable the way a preset is."

### Design-stance verification (no new interface / superpowered by default)

Confirmed against the code, briefly: an agent spawned by switchboard is an ordinary Claude
Code session (herdr starts a real `claude` process; switchboard's own README says herdr
"types into the chat box and presses enter, so a message from sb arrives looking exactly
like one Andrew typed") plus a system-prompt fragment assembled from `defaults/roles.toml`
+ bound presets + enabled plugin fragments — nothing that changes the interface itself.
"Superpowered by default" is accurate for what ships pre-bound (per `defaults/presets.toml`
and `defaults/plugins.toml`, read in full in an earlier pass): the orchestrator role is
pointed at the adversarial-review procedure by name already, `report-bug` plugin ships
enabled and bound, and the whole protocol (delegate/tell/done/block/inbox/status) is part
of the base spawn, not something assembled per-project.

Word count of final draft: 141.

## v6 revision (reset — positive-list-first, not gap-hunting)

Brief: /private/tmp/claude-501/-Users-andrew-Code-switchboard/2475cfa7-549f-4d2a-adcb-64d167470f52/scratchpad/task-positioning-v6.md
New draft: /Users/andrew/Code/switchboard/.positioning-draft.md — 199 words (target
150-200). Register D/A. Built the positive list first as instructed, verified each item,
then added the "coverage exists in pieces, but not the whole set" close.

### The positive list, and verification of each item

All eight candidates from the brief were checked; none had to be cut for lacking
verification:

1. **Many independent roots.** DESIGN-TRUTH.md line 123: "How many spaces and agents are
   alive at once is fine as it is right now" (no cap). Line 178: "Siblings are not
   invisible to each other; any other top orchestrator's entire tree is invisible" — each
   `sb start` makes a fully independent worktree/tree, and "The board is shared, and from
   it Andrew crosses freely into any tree" (line 183-184). Verified in an earlier pass of
   this task against Firstmate too: its designed unit is one firstmate-per-`FM_HOME`, with
   secondmates nested beneath it, not parallel independent roots by default.
2. **Ordinary Claude Code session, no new interface.** README.md: herdr "types into the
   chat box and presses enter, so a message from sb arrives looking exactly like one
   Andrew typed."
3. **Superpowered by default.** `defaults/presets.toml` and `defaults/plugins.toml`
   (read in full in an earlier pass): the orchestrator role is pointed at the
   adversarial-review preset by name already; `report-bug` ships enabled and bound.
   Nothing has to be assembled per repo to get this.
4. **Procedures as reusable preset files.** `defaults/presets/adversarial.md`, read in
   full — a named, on-demand, multi-round choreography (kept-alive proposer, fresh
   uncontaminated reviewer per round, rotating lens, convergence rule, hard cap) invoked
   with `sb presets adversarial` rather than re-explained in a prompt each time.
5. **Mechanical enforcement.** README.md: "A Stop gate. Agents finished turns without
   reporting, four times in one day... Ending a turn nobody reported is now refused
   mechanically rather than asked for politely."
6. **One honest human channel.** README.md: "A human is reached exactly one way... There
   is no human inbox — it existed once and was removed, because messages nobody can see
   are worse than no messages." `sb block` + the board.
7. **Plugins own a verb and durable state.** `defaults/plugins.toml`'s own definition: "a
   Python package — `defaults/plugins/<name>/` ... that owns a CLI verb and a directory of
   durable state." `report-bug` is the live shipped instance.
8. **Built on herdr.** README.md architecture section: "`switchboard/herdr.py` — the only
   module that knows herdr exists... the insurance policy: if herdr goes away, this file
   is what gets replaced, not the system." Panes, tabs and worktrees are herdr's, not
   reimplemented.

### What I found in his files that hadn't been used yet

`notes/braindump.md` lines 15-36 ("Scope: a personal tool, not a product") reframes the
whole "it already exists elsewhere" objection directly, in language close to what Andrew
said in this round's brief: "It matters enormously whether a *product* is differentiated.
It matters much less whether a personal tool is — the question becomes 'does anything
existing fit MY workflow well enough to adopt instead,' which is a far lower bar." This is
effectively Andrew re-deriving, weeks later in the chat, a point he'd already written down
here. I did not quote it in the 200-word draft (no room, and it's about *why the bar is
lower* rather than *what the set is*), but flagging it since it's a second, independent
piece of prior-written evidence for this round's reset, beyond what the brief already
pointed at.

### Where coverage falls short of the set (kept generous, per instruction)

Named plainly in the draft's close: Firstmate has real typed human gates and lets a
captain type directly into any crewmate's pane (both verified in the prior round with
direct doc fetches); Agent Teams gives teammates persistent, addressable identities
(verified against code.claude.com/docs/en/agent-teams in an earlier pass). Neither struck
from the piece — both named as real, working coverage of individual pieces of the set. The
claim in the draft is only that the whole set together isn't covered anywhere at once, not
that any individual item is unprecedented.

Word count of final draft: 199.
