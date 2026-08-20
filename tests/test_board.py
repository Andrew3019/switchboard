"""Board tests — the pure half of the clickable view.

`switchboard/board.py` had no tests at all, which is a problem specific to this file: it
is the one surface where being *subtly* wrong is invisible. A misdrawn row still looks
like a row, and the click that follows focuses a different agent than the one under the
cursor — silently, and indistinguishably from a correct click.

So what is pinned here is the mapping, not the appearance: decode → layout → agent_at.
That half is pure, which is why the terminal, herdr and the store are absent from it. The
last class is the exception, and says why it has to be.
"""

from __future__ import annotations

import json
import os
import pty
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tty
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import board, panel, richboard, status  # noqa: E402

# `rich` is optional — `richboard.available()` is asked rather than assumed, and where the
# answer is no `richboard.layout` returns None by contract and the plain renderer draws.
# The tests below that compare the two renderers therefore check the plain half always and
# the rich half only where there is a rich renderer to check, exactly as
# `tests/test_richboard.py` does. CI installs the test runner and nothing else, so this is
# the ordinary case there rather than an exotic one.
HAVE_RICH = richboard.available()


def agent(name, *, depth=0, state="working", herdr_state="working", alive=True,
          stalled=False, gone=False, unread=0, task=None, blocked_why=None,
          summary=None, parent=None, archived=False, undelivered=0, undelivered_age=0,
          idle_excuse=None, pane_id=None, workspace="api"):
    """One agent. `archived=True` sets what being absent from herdr past the spawn
    grace actually looks like, so the real `AgentStatus.archived` decides — nothing
    here mocks the predicate."""
    return status.AgentStatus(
        name=name, role="worker", parent=parent, depth=depth, state=state,
        herdr_state=None if archived else herdr_state,
        alive=False if archived else alive,
        stalled=stalled, gone=gone, unread=unread,
        age=int(status.SPAWN_GRACE) + 1 if archived else 10,
        idle=5, last_activity=0, workspace=workspace, task=task,
        blocked_why=blocked_why, summary=summary,
        undelivered=undelivered, undelivered_age=undelivered_age,
        idle_excuse=idle_excuse, pane_id=pane_id,
    )


def snap(*agents):
    return status.Snapshot(now=0, agents=list(agents))


def blocks(rows):
    """The display ROWS drawn, one entry each, in order.

    An agent owns one screen line and a collapsed group one, but the breaks between
    first-level groups own none, so "what is on screen" and "how many lines is that" are
    not the same list. Consecutive lines with the same owner count once — which is the
    invariant the mapping rests on: a row's lines are adjacent and all carry it.
    """
    out = []
    for _, a in rows:
        if a is not None and (not out or a is not out[-1]):
            out.append(a)
    return out


class ParseSgrTest(unittest.TestCase):
    def test_a_click_decodes_to_button_column_and_row(self):
        events, rest = board.parse_sgr("\033[<0;12;7M")
        self.assertEqual(rest, "")
        self.assertEqual([e["button"] for e in events], [0])
        self.assertEqual((events[0]["col"], events[0]["row"]), (12, 7))
        self.assertTrue(board.is_left_click(events[0]))

    def test_a_sequence_split_across_two_reads_is_held_not_mangled(self):
        """os.read gives no guarantee of landing on an escape-sequence boundary."""
        events, rest = board.parse_sgr("\033[<0;12")
        self.assertEqual(events, [])
        self.assertEqual(rest, "\033[<0;12")
        events, rest = board.parse_sgr(rest + ";7M")
        self.assertTrue(board.is_left_click(events[0]))
        self.assertEqual(rest, "")

    def test_keystrokes_survive_alongside_mouse_events(self):
        events, _ = board.parse_sgr("q\033[<0;1;1M")
        self.assertEqual(events[0]["raw"], "q")
        self.assertIsNone(events[0]["button"])
        self.assertTrue(board.is_left_click(events[1]))

    def test_the_wheel_is_only_read_on_press(self):
        [up], _ = board.parse_sgr("\033[<64;1;1M")
        [down], _ = board.parse_sgr("\033[<65;1;1M")
        [release], _ = board.parse_sgr("\033[<64;1;1m")
        self.assertEqual((board.wheel(up), board.wheel(down)), (-1, 1))
        self.assertEqual(board.wheel(release), 0)


class GlyphTest(unittest.TestCase):
    def test_gone_outranks_everything(self):
        """A row saying `working` about a pane herdr cannot see is the one lie this view
        must never tell, so `gone` wins even over a block."""
        a = agent("w", gone=True, state="blocked", unread=3)
        self.assertEqual(board.glyph(a), "✗")
        self.assertEqual(board.marker(a), "GONE — herdr has no such agent")

    def test_every_glyph_has_a_colour_and_they_are_all_distinct(self):
        kinds = [agent("a", gone=True), agent("b", state="blocked"),
                 agent("c", stalled=True), agent("d", state="done"),
                 agent("e", alive=None), agent("f")]
        glyphs = [board.glyph(a) for a in kinds]
        self.assertEqual(len(set(glyphs)), len(glyphs))
        for g in glyphs:
            self.assertIn(g, board._GLYPH_COLOR)

    def test_only_one_marker_is_ever_shown_and_it_is_the_most_actionable(self):
        a = agent("w", state="blocked", blocked_why="need a key", unread=2,
                  task="do the thing")
        self.assertEqual(board.marker(a), "BLOCKED — need a key")


class RowSaysOneThingTest(unittest.TestCase):
    """The row must not contradict itself.

    Andrew reported seeing one agent drawn as `working` and `STALLED` at once. It was not
    a logic bug: the STATE column printed the store's self-report ("task still open") and
    the note printed the pane observation ("no turn is running"), two vocabularies on one
    line with nothing reconciling them. What is pinned here is that the column now shows
    the joined word and STALLED is only ever a qualifier beside it.
    """

    def line(self, a):
        """The agent's row. One line now, and the contradiction pinned here would be a
        contradiction wherever on it the two halves were drawn."""
        rows = board.layout(snap(a), top=0, height=10, width=200, msg="")
        return "\n".join(t for t, row in rows if row is a)

    def test_a_stalled_agent_reads_idle_and_never_working_as_well(self):
        line = self.line(agent("w", state="working", herdr_state="idle", stalled=True))
        self.assertIn("idle", line)
        self.assertNotIn("working", line)
        self.assertIn("STALLED", line)

    def test_the_word_is_whatever_the_pane_was_observed_to_be_doing(self):
        """An open task reads `working` or `idle` on herdr's observation alone — and on
        nothing at all when there was no observation to make: with herdr unreachable
        (`alive is None`) the store's own word stands, the same rule `stalled` and `gone`
        are built on, and `render` says at the top that ALIVE is unknown."""
        # Explained idle — a lead waiting on live children. Same word, no warning.
        lead = self.line(agent("lead", state="working", herdr_state="idle",
                               stalled=False, task="mind the children"))
        self.assertIn("idle", lead)
        self.assertNotIn("STALLED", lead)
        self.assertIn("working", self.line(agent("w", herdr_state="working")))
        unreachable = self.line(agent("u", state="working", herdr_state=None, alive=None))
        self.assertIn("working", unreachable)
        self.assertNotIn("idle", unreachable)


class IdleReadsAsOneThingTest(unittest.TestCase):
    """Idle told apart from stalled, which is the question Andrew asked of this row.

    Both rows say `idle` and they mean opposite things: one is a lead doing exactly what
    the protocol asked of it, the other quietly died. What is pinned here is that the row
    says which, rather than leaving a reader to infer it from the tree.
    """

    def line(self, a):
        """The agent's row. One line now, and the contradiction pinned here would be a
        contradiction wherever on it the two halves were drawn."""
        rows = board.layout(snap(a), top=0, height=10, width=200, msg="")
        return "\n".join(t for t, row in rows if row is a)

    def test_an_explained_idle_row_says_what_explains_it(self):
        line = self.line(agent("lead", state="working", herdr_state="idle",
                               idle_excuse="waiting on children", task="mind them"))
        self.assertIn("idle", line)
        self.assertIn("waiting on children", line)
        self.assertNotIn("STALLED", line)

    def test_an_unexplained_idle_row_reads_as_needing_attention(self):
        a = agent("w", state="working", herdr_state="idle", stalled=True,
                  task="fix the parser")
        line = self.line(a)
        self.assertIn("STALLED", line)
        self.assertTrue(board.wants_you(a))       # the ← marker, and the ◌ glyph
        self.assertEqual(board.glyph(a), "◌")

    def test_a_pane_herdr_cannot_read_asks_for_a_keypress_instead_of_reporting_a_stall(self):
        """The narrower label REPLACES the word and nothing else: same row, same section,
        same glyph, and it says what a person has to do. The stalled row above is the
        control — detection saying no, or never being asked, still reads STALLED."""
        a = agent("w", state="working", herdr_state="idle", stalled=True,
                  task="fix the parser")
        a.awaiting_keypress = True
        line = self.line(a)
        self.assertIn("AWAITING KEYPRESS", line)
        self.assertIn("press a key in its pane", line)
        self.assertNotIn("STALLED", line)
        self.assertTrue(board.wants_you(a))
        self.assertEqual(richboard.marker_short(a), "KEYPRESS")
        self.assertEqual(richboard.needs_kind(a), "blocked")
        self.assertIn("press a key in its pane", richboard.needs_reason(a))
        self.assertIn(a, richboard.needs_list([a]))

        # AND IT WAITS ITS TURN LIKE THE STALL UNDER IT. The reading is one frame of
        # herdr's screen classifier, so it goes through the NEEDS YOU debounce rather than
        # around it: until the summons has settled the row says nothing at all and nobody
        # is called over. `needs_for=None` above is an unwatched row, which is shown.
        a.needs_for = 0
        self.assertFalse(a.settled)
        self.assertEqual(board.marker(a), "")
        self.assertFalse(board.wants_you(a))
        self.assertEqual(richboard.needs_kind(a), "")

    def test_mail_alone_no_longer_marks_the_agent_row(self):
        """It used to: unread mail took over the note and the `←`, so an agent with mail
        looked like an agent in trouble. Mail names itself where it is drawn, and the
        row goes back to saying what the agent is doing."""
        a = agent("w", unread=2, task="fix the parser")
        self.assertFalse(board.wants_you(a))
        self.assertEqual(board.tail_note(a), "fix the parser")


class OneLineTest(unittest.TestCase):
    """Every agent is exactly one line, and everything it has to say is on it.

    The row was split in two and Andrew did not like it, so it is back: identity, then
    as much of `detail_bits` as the width allows, in priority order. What a test can
    catch is the "exactly one" — a block that is sometimes one line and sometimes two
    is a tree a reader cannot scan and a click path that has to be re-argued.
    """

    def rows(self, *agents, height=20, width=80):
        return board.layout(snap(*agents), top=0, height=height, width=width, msg="")

    def lines(self, rows, a):
        return [board._ANSI.sub("", t) for t, row in rows if row is a]

    def test_every_agent_costs_exactly_one_line_whatever_it_has_to_say(self):
        loud = agent("loud", state="blocked", blocked_why="need a key", unread=3,
                     undelivered=1, undelivered_age=60, task="do the thing")
        quiet = agent("quiet")
        rows = self.rows(loud, quiet)
        self.assertEqual(len(self.lines(rows, loud)), 1)
        self.assertEqual(len(self.lines(rows, quiet)), 1)

    def test_identity_and_detail_share_the_one_row(self):
        a = agent("w", state="blocked", blocked_why="need a key", unread=2,
                  task="fix the parser")
        [line] = self.lines(self.rows(a), a)
        self.assertIn("blocked", line)                      # name, state, timing
        for said in ("BLOCKED", "need a key", "unread", "fix the parser"):
            self.assertIn(said, line)

    def test_priority_is_trouble_then_mail_then_context(self):
        a = agent("w", state="blocked", blocked_why="need a key", unread=2,
                  task="fix the parser")
        self.assertEqual([kind for _, _, kind in board.detail_bits(a)],
                         ["marker", "mail", "tail"])
        [line] = self.lines(self.rows(a), a)
        self.assertLess(line.index("BLOCKED"), line.index("mail:"))
        self.assertLess(line.index("mail:"), line.index("fix the parser"))

    def test_context_is_dropped_first_and_mail_is_never_crowded_out(self):
        """Sixty columns, a verbose block and mail waiting. The task head goes, because
        it is the piece a reader can get elsewhere — and the mail stays, because it is
        quite possibly the answer that ends the block."""
        a = agent("w", state="blocked", unread=1, undelivered=1, undelivered_age=900,
                  blocked_why="whether to merge #33 before or after the board work lands",
                  task="put every agent back on one line")
        [line] = self.lines(self.rows(a, width=60), a)
        self.assertIn("BLOCKED", line)
        self.assertIn("UNDELIVERED", line)
        self.assertNotIn("put every agent", line)

    def test_an_explained_idle_agent_shows_its_excuse_on_the_row(self):
        """The distinction Andrew asked for survives the return to one line: the excuse
        rides in rank three, and an agent with an excuse has no marker competing for the
        room, so it is what the row shows."""
        a = agent("lead", state="working", herdr_state="idle",
                  idle_excuse="waiting on children", task="mind them")
        [line] = self.lines(self.rows(a, width=60), a)
        self.assertIn("idle", line)
        self.assertIn("waiting on children", line)
        self.assertNotIn("STALLED", line)

    def test_undelivered_is_named_and_the_rest_counted_by_subtraction(self):
        """UNDELIVERED is the loud one: unread means we rang and it has not looked;
        undelivered means it was never told. Never double-counted — undelivered is a
        subset of unread."""
        a = agent("w", unread=3, undelivered=1, undelivered_age=720)
        self.assertEqual(board.mail_note(a), "mail: UNDELIVERED 1, 12m · 2 unread")
        self.assertEqual(board.mail_note(agent("q")), "")

    def test_a_click_resolves_to_the_agent_on_that_row(self):
        """THE PROOF, at the shape the board is actually drawn in."""
        rows = self.rows(agent("one", unread=2), agent("two"), agent("three"))
        drawn = [(i + 1, a.name) for i, (_, a) in enumerate(rows) if a is not None]
        self.assertEqual([n for _, n in drawn], ["one", "two", "three"])
        for row, name in drawn:
            self.assertEqual(board.agent_at(rows, row).name, name)

    def test_a_row_never_widens_the_screen(self):
        rows = board.layout(snap(agent("日本語", unread=99, undelivered=99,
                                       undelivered_age=99999,
                                       task="日本語の説明" * 20)),
                            top=0, height=10, width=40, msg="")
        for text, _ in rows:
            self.assertLessEqual(board._visible_len(text), 40)


class GroupBreakTest(unittest.TestCase):
    """A blank line between first-level groups, and nowhere else.

    Each direct child of the top orchestrator usually bounds one task, along with its
    whole subtree, and the tree is much easier to read in those blocks. Two things can go
    wrong and both are pinned here: a break INSIDE a subtree, which splits one task in
    half, and a break that belongs to an agent, which would make a click on empty space
    focus somebody.
    """

    def tree(self, **kw):
        """main, and two first-level groups, one of them two deep."""
        return snap(agent("main"),
                    agent("lead", depth=1, parent="main"),
                    agent("w1", depth=2, parent="lead"),
                    agent("w2", depth=2, parent="lead"),
                    agent("solo", depth=1, parent="main"))

    def shape(self, rows):
        """The tree part of the screen as names and blanks, in order."""
        out = []
        for text, a in rows:
            plain = board._ANSI.sub("", text).strip()
            if a is not None:
                out.append(getattr(a, "name", "GROUP"))
            elif out and plain == "":
                out.append("")
        while out and out[-1] == "":
            out.pop()
        return out

    def test_the_break_falls_between_groups_and_never_inside_one(self):
        rows = board.layout(self.tree(), top=0, height=board.CHROME + 8, width=60, msg="")
        self.assertEqual(self.shape(rows),
                         ["main", "", "lead", "w1", "w2", "", "solo"])

    def test_a_break_is_owned_by_nobody_so_clicking_it_does_nothing(self):
        rows = board.layout(self.tree(), top=0, height=board.CHROME + 8, width=60, msg="")
        blank = next(i for i, (t, _) in enumerate(rows)
                     if board._ANSI.sub("", t).strip() == ""
                     and any(a is not None for _, a in rows[:i]))
        self.assertIsNone(board.agent_at(rows, blank + 1))

    def test_every_other_row_still_resolves_to_the_agent_drawn_on_it(self):
        rows = board.layout(self.tree(), top=0, height=board.CHROME + 8, width=60, msg="")
        drawn = [(i + 1, a.name) for i, (_, a) in enumerate(rows) if a is not None]
        self.assertEqual([n for _, n in drawn],
                         ["main", "lead", "w1", "w2", "solo"])
        for row, name in drawn:
            self.assertEqual(board.agent_at(rows, row).name, name)

    def test_a_break_costs_a_line_of_the_window_rather_than_overflowing_it(self):
        """The break is paid for out of the same screen, or the footer ends up claiming
        rows that were pushed off the bottom."""
        height = board.CHROME + 4                   # main, break, lead, w1
        rows = board.layout(self.tree(), top=0, height=height, width=60, msg="")
        self.assertEqual(len(rows), height)
        self.assertEqual(self.shape(rows), ["main", "", "lead", "w1"])
        self.assertIn("+2 more below", "\n".join(t for t, _ in rows))

    def test_a_group_at_the_top_of_the_window_is_not_pushed_down_by_its_break(self):
        """Scrolled so a group starts the window: the top of the screen already says a
        new group starts here, and a blank first line would only cost a row."""
        rows = board.layout(self.tree(), top=1, height=board.CHROME + 4, width=60,
                            msg="")
        self.assertEqual(self.shape(rows), ["lead", "w1", "w2"])


class LayoutTest(unittest.TestCase):
    def test_a_click_resolves_to_the_agent_drawn_on_that_row(self):
        rows = board.layout(snap(agent("one"), agent("two", depth=1), agent("three")),
                            top=0, height=board.CHROME + 6, width=100, msg="")
        drawn = [(i + 1, a.name) for i, (_, a) in enumerate(rows) if a is not None]
        self.assertEqual([a.name for a in blocks(rows)], ["one", "two", "three"])
        for row, name in drawn:
            self.assertEqual(board.agent_at(rows, row).name, name)

    def test_a_click_off_the_agents_resolves_to_nobody(self):
        rows = board.layout(snap(agent("one")), top=0, height=12, width=100, msg="")
        self.assertIsNone(board.agent_at(rows, 1))          # the header
        self.assertIsNone(board.agent_at(rows, len(rows)))  # the help line
        self.assertIsNone(board.agent_at(rows, 0))          # rows are 1-based
        self.assertIsNone(board.agent_at(rows, 9999))

    def test_scrolling_moves_which_agent_a_row_means(self):
        agents = [agent(f"a{i}") for i in range(20)]
        first = board.layout(snap(*agents), top=0, height=10, width=100, msg="")
        later = board.layout(snap(*agents), top=3, height=10, width=100, msg="")
        # The first row the tree owns — which one that is moved when the stats section
        # went in above it, and what is pinned here is that it means a different agent
        # after a scroll, not which line of the screen it happens to be.
        row = next(i + 1 for i, (_, a) in enumerate(first) if a is not None)
        self.assertEqual(board.agent_at(first, row).name, "a0")
        self.assertEqual(board.agent_at(later, row).name, "a3")

    def test_scrolling_past_the_end_stops_rather_than_emptying_the_view(self):
        agents = [agent(f"a{i}") for i in range(6)]
        rows = board.layout(snap(*agents), top=999, height=10, width=100, msg="")
        self.assertTrue([a for _, a in rows if a is not None])

    def test_no_line_may_wrap_because_a_wrapped_line_shifts_every_click_below_it(self):
        wide = agent("w", task="x" * 400)
        rows = board.layout(snap(wide), top=0, height=10, width=40, msg="m" * 200)
        for text, _ in rows:
            self.assertLessEqual(board._visible_len(text), 40)

    def test_a_wide_character_row_does_not_wrap_and_the_rows_below_it_still_map(self):
        """The defect this file was short of: `len()` said the row fit, the terminal
        disagreed, and every click below it landed one agent low. The task here is 30
        characters and 60 columns — inside an ASCII budget of 40, twice over it in a
        terminal — and the row after it is the one whose click has to survive."""
        rows = board.layout(snap(agent("cjk", task="日本語の説明" * 5), agent("below")),
                            top=0, height=board.CHROME + 4, width=40, msg="")
        for text, _ in rows:
            self.assertLessEqual(board._visible_len(text), 40)
        row = next(i + 1 for i, (_, a) in enumerate(rows) if a is not None
                   and not board._is_group(a) and a.name == "below")
        self.assertEqual(board.agent_at(rows, row).name, "below")

    def test_an_emoji_sequence_is_one_glyph_two_columns_wide(self):
        """Zero-width joiners, skin tone and a flag are all one glyph each — measuring
        their codepoints would over-count and truncate a row that fits."""
        self.assertEqual(board._visible_len("👩‍👩‍👧‍👦"), 2)
        self.assertEqual(board._visible_len("👨🏽‍💻"), 2)
        self.assertEqual(board._visible_len("🇯🇵"), 2)
        rows = board.layout(snap(agent("👩‍👩‍👧‍👦-team", task="🚀 " * 30), agent("plain")),
                            top=0, height=10, width=40, msg="")
        for text, _ in rows:
            self.assertLessEqual(board._visible_len(text), 40)

    def test_the_state_column_lines_up_under_a_wide_name(self):
        """Padding in characters leaves the columns ragged, which is the same
        mismeasurement seen before it becomes a wrap."""
        rows = board.layout(snap(agent("日本語", state="working"),
                                 agent("ascii", state="working")),
                            top=0, height=board.CHROME + 4, width=200, msg="")
        drawn = [t for t, a in rows if a is not None and "working" in t]
        self.assertEqual(*[board._visible_len(t[:t.index("working")]) for t in drawn])

    def test_the_screen_is_exactly_the_height_it_was_given(self):
        for height in (6, 10, 24, 50):
            rows = board.layout(snap(agent("one"), agent("two")), top=0, height=height,
                                width=80, msg="")
            self.assertEqual(len(rows), height)

    def test_an_empty_board_says_what_to_do_instead_of_nothing(self):
        rows = board.layout(snap(), top=0, height=10, width=80, msg="")
        self.assertIn("sb start", "".join(t for t, _ in rows))

    def test_the_header_counts_come_from_status_so_the_two_readouts_cannot_disagree(self):
        s = snap(agent("a", stalled=True), agent("b", gone=True, alive=False))
        rows = board.layout(s, top=0, height=10, width=200, msg="")
        self.assertIn(status.summary_line(s), board._ANSI.sub('', rows[0][0]))


class HeadlineTest(unittest.TestCase):
    """Alive is the number a person reads first, and at 60 columns it is the one that
    survives. The rest are ordered by how much they matter and dropped whole from the
    tail — a half-written `2 bloc` says nothing, and a dangling `·` says less."""

    def head(self, s, width):
        rows = board.layout(s, top=0, height=10, width=width, msg="")
        return board._ANSI.sub("", rows[0][0])

    def test_the_headline_is_alive_and_it_comes_first(self):
        s = snap(agent("a"), agent("b", stalled=True), agent("c", archived=True))
        head = self.head(s, 200)
        self.assertIn("2 alive", head)
        self.assertLess(head.index("alive"), head.index("agents"))
        self.assertIn(status.summary_line(s), head)

    def test_a_narrow_board_drops_whole_counts_from_the_least_important_end(self):
        s = snap(agent("a"), agent("b", stalled=True))
        head = self.head(s, 34)
        self.assertIn("2 alive", head)
        self.assertNotIn("agents", head)          # the total goes before the trouble does
        self.assertFalse(head.rstrip().endswith("·"))

    def test_the_headline_alone_is_never_dropped(self):
        head = self.head(snap(agent("a")), 20)
        self.assertIn("alive", head)


class StatsSectionTest(unittest.TestCase):
    """The top section, and the ONE WAY IT CAN LIE.

    `stats.Stats` is fourteen fields that are `None` until their group has been sampled —
    on a board's first tick, all fourteen — and a `None` drawn as `0` turns "we could not
    measure this" into a confident measurement, on a screen where nothing would look
    wrong. Both halves are pinned here: the unknown is not a zero, and the zero is not an
    unknown.

    Pure, so this is the section's content and not its appearance: `stats_rows` is what
    both renderers ask, which is what stops the panel and the plain board coming to report
    different numbers about one fleet.
    """

    FULL = {"turns_last_hour": 47, "spawns_last_hour": 6, "messages_last_hour": 3,
            "store_age": 2.0, "code_added": 1740, "code_deleted": 776,
            "commits_last_hour": 25, "git_age": 30.0, "cpu_percent": 384.0,
            "memory_bytes": 1288490188, "memory_available_bytes": 6227702579,
            "processes": 9, "cpu_cores": 10, "proc_age": 1.0}

    def pieces(self, stats):
        return {label: bits for label, bits in board.stats_rows(stats)}

    def test_an_unknown_is_left_out_and_is_never_drawn_as_a_zero(self):
        # The first tick of every board: a snapshot published, no sample in it yet.
        for empty in ({}, None, {k: None for k in self.FULL}):
            got = self.pieces(empty)
            self.assertEqual(list(got.values()), [[], []], empty)
            # And the line still says something deliberate rather than going blank.
            line = board._ANSI.sub("", board._stats_line(board.STATS_HOUR, [], 96))
            self.assertEqual(line.split(), ["LAST", "HOUR", "not", "measured"])
            self.assertNotIn("0", line)

    def test_a_real_zero_is_still_a_number_and_is_drawn(self):
        """The other half, and the reason the first one cannot be done by falsiness: an
        hour in which nobody spawned anything is a fact, and the board reports it."""
        got = self.pieces({**self.FULL, "spawns_last_hour": 0, "messages_last_hour": 0})
        self.assertIn("0 spawns", got[board.STATS_HOUR])
        # `mail` is uncountable, so it does not pluralise at any count.
        self.assertIn("0 mail", got[board.STATS_HOUR])
        self.assertNotIn("mails", " ".join(got[board.STATS_HOUR]))
        # Never "calls": nothing logs an sb invocation, so that number does not exist.
        self.assertNotIn("calls", " ".join(got[board.STATS_HOUR]))

    def test_the_numbers_read_the_way_a_person_would_size_them(self):
        got = self.pieces(self.FULL)
        self.assertEqual(got[board.STATS_HOUR],
                         ["47 turns", "+1.7k/-776", "25 commits", "6 spawns", "3 mail"])
        # CPU as a share of the WHOLE MACHINE, because `ps` sums over the tree and 384%
        # alone reads as a broken gauge; memory named `rss`, because summed RSS is an
        # upper bound and not the fleet's footprint.
        self.assertEqual(got[board.STATS_NOW],
                         ["38% cpu", "1.2G rss", "5.8G free", "17% mem", "9 procs"])
        # And a narrow pane keeps whole pieces from the important end — a half-written
        # `+1.7k/-7` says nothing and a dangling `·` says less.
        room = board._visible_len("47 turns · +1.7k/-776")
        self.assertEqual(board.stats_fit(got[board.STATS_HOUR], room),
                         ["47 turns", "+1.7k/-776"])

    def test_the_code_piece_needs_both_halves_and_the_cpu_share_needs_its_cores(self):
        """Half a `+/-` is a half measurement wearing whole punctuation, and a share of
        the machine has no meaning without the machine's core count."""
        for missing in ("code_added", "code_deleted"):
            got = self.pieces({**self.FULL, missing: None})
            self.assertFalse([p for p in got[board.STATS_HOUR] if p.startswith("+")],
                             missing)
        no_cores = self.pieces({**self.FULL, "cpu_cores": None})
        self.assertNotIn("cpu", " ".join(no_cores[board.STATS_NOW]))
        self.assertEqual(no_cores[board.STATS_NOW][0], "1.2G rss")   # the rest survives

    def test_the_cpu_share_is_clamped_to_a_percentage_of_the_machine(self):
        """Summed `ps` %CPU is a decaying average and can momentarily overshoot the box.
        `104% cpu` reads as a broken gauge; 100 is the honest ceiling."""
        hot = self.pieces({**self.FULL, "cpu_percent": 1040.0, "cpu_cores": 10})
        self.assertEqual(hot[board.STATS_NOW][0], "100% cpu")
        idle = self.pieces({**self.FULL, "cpu_percent": 0.0, "cpu_cores": 10})
        self.assertEqual(idle[board.STATS_NOW][0], "0% cpu")

    def test_the_memory_share_is_of_what_the_fleet_could_use_not_of_the_whole_box(self):
        """`rss / (rss + free)`, deliberately: memory another program is holding is not
        memory this fleet could have, and counting it would report a machine that is nearly
        full as a quiet one. Half the usable memory is 50% however big the box is."""
        got = self.pieces({**self.FULL, "memory_bytes": 4 * 1024 ** 3,
                           "memory_available_bytes": 4 * 1024 ** 3})
        self.assertIn("50% mem", got[board.STATS_NOW])
        # And with nothing left, the fleet's share of what it could use is all of it.
        full = self.pieces({**self.FULL, "memory_available_bytes": 0})
        self.assertIn("100% mem", full[board.STATS_NOW])

    def test_an_unreadable_free_figure_costs_the_share_and_not_the_rss(self):
        """A machine whose free memory could not be read still reports what the fleet
        holds — the two are separate measurements and one is not evidence about the
        other."""
        got = self.pieces({**self.FULL, "memory_available_bytes": None})
        self.assertIn("1.2G rss", got[board.STATS_NOW])
        self.assertNotIn("mem", " ".join(got[board.STATS_NOW]))
        self.assertNotIn("free", " ".join(got[board.STATS_NOW]))

    def test_the_section_has_a_header_of_its_own_and_a_blank_line_under_it(self):
        """Andrew, reading the real board: the numbers want a `STATS` header like
        `AGENTS`, and a line of air between the two sections. Pinned as the ORDER of the
        head, because every row below it is placed off that count — `display.board_chrome`
        counts these four lines and a fifth one appearing here would push the tree off the
        bottom of the pane while the footer still claimed it was on screen."""
        rows = board.layout(snap(agent("top")), top=0, height=board.CHROME + 4,
                            width=80, msg="", stats=self.FULL)
        head = [board._ANSI.sub("", t).rstrip() for t, _ in rows[:6]]
        self.assertTrue(head[0].startswith("switchboard"), head[0])
        self.assertEqual(head[1], " STATS")
        self.assertTrue(head[2].startswith(" LAST HOUR"), head[2])
        self.assertTrue(head[3].startswith(" RIGHT NOW"), head[3])
        self.assertEqual(head[4], "")
        self.assertEqual(head[5], " AGENTS")
        # And the whole block goes back together on a pane too short for it: a label over
        # nothing and a gap holding nothing apart are what the last line must not be spent
        # on. The tree is what a board is.
        short = [board._ANSI.sub("", t).rstrip()
                 for t, _ in board.layout(snap(agent("top")), top=0, height=board.CHROME,
                                          width=80, msg="", stats=self.FULL)]
        self.assertNotIn(" STATS", short)
        self.assertFalse([ln for ln in short if ln.startswith(" LAST HOUR")], short)
        self.assertTrue(any("top" in ln for ln in short), short)


class RefreshTest(unittest.TestCase):
    """The one impure test in this file, and it earns the exception.

    Everything above is pure because the board's bugs are drawing bugs. This one is about
    where the rows come from, which used to be the store and is now a file one elected
    collector publishes. It used to prove that a two-second tick here wrote nothing —
    three boards older than a fix to the spawn grace once marked every agent spawned that
    night `failed` during their own startup. That guarantee did not weaken; it moved,
    with the connect, to `tests/test_readonly.py::CollectorTick`, and `tests/test_panel.py
    ::RendererImports` now makes it structural: this file cannot reach the store to write
    to it. What is left to check here is the renderer's half of the bargain — that it
    reads what was published, and that it says so when what it read is old.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = panel.Paths(Path(self.tmp.name) / "panel")
        self.sup = panel.Supervisor(self.paths)

    def _publish(self, **counters):
        meta = {"pid": 7, "started_at": 0.0, "polls": 3, "errors": 0,
                "collected_at": panel.now(), "wrote_at": panel.now(), "tick_ms": 9.0,
                "last_error": None, "last_error_at": None}
        meta.update(counters)
        snap = status.Snapshot(now=100, agents=[agent("w1", gone=True, alive=False)])
        panel.publish(self.paths, panel.envelope(snap.as_dict(), meta))

    def test_a_refresh_draws_what_the_collector_published(self):
        self._publish()
        with mock.patch.object(panel, "ensure_collector", lambda *a, **k: False):
            snap, note_text, stats = board.refresh(self.sup)
        self.assertEqual(note_text, "")
        self.assertEqual(stats, {})                   # this collector published none
        self.assertTrue(snap.agents[0].gone)          # the screen says it, exactly as before
        rows = board.layout(snap, top=0, height=10, width=120, msg="", note_text=note_text)
        row = next(i + 1 for i, (_, a) in enumerate(rows) if a is not None)
        self.assertEqual(board.agent_at(rows, row).name, "w1")

    def test_an_old_snapshot_is_labelled_rather_than_drawn_as_now(self):
        """The failure a shared cache introduces, and the one thing the design asked to be
        loud: forty panes quietly agreeing on stale data."""
        self._publish(collected_at=panel.now() - 40)
        with mock.patch.object(panel, "ensure_collector", lambda *a, **k: False):
            snap, note_text, _stats = board.refresh(self.sup)
        self.assertIn("snapshot 40s old", note_text)
        rows = board.layout(snap, top=0, height=10, width=120, msg="", note_text=note_text)
        self.assertIn("snapshot 40s old", "".join(t for t, _ in rows))

    def test_a_refresh_says_a_panel_is_still_being_looked_at(self):
        """The collector's only reason to keep running, and so the only reason it cannot
        outlive the panels."""
        self._publish()
        with mock.patch.object(panel, "ensure_collector", lambda *a, **k: False):
            board.refresh(self.sup)
        self.assertLess(panel.demand_age(self.paths), 5)

    def test_a_refresh_with_nothing_published_yet_draws_a_screen_anyway(self):
        with mock.patch.object(panel, "ensure_collector", lambda *a, **k: False):
            snap, note_text, _stats = board.refresh(self.sup)
        self.assertEqual(snap.agents, [])
        self.assertIn("collector", note_text)
        self.assertEqual(len(board.layout(snap, top=0, height=12, width=80, msg="",
                                          note_text=note_text)), 12)


class CollapseLayoutTest(unittest.TestCase):
    """Collapse in the panel — and the mapping it could break.

    `layout` used to window `snap.agents` directly and `agent_at` used to be able to
    assume every carried object was an agent. Neither is true once a display row can
    stand for a whole subtree, and both failures are of the silent kind this file exists
    for: a click that focuses somebody, just not the row under the cursor.
    """

    def drawn(self, rows):
        return blocks(rows)

    def text(self, rows):
        return "\n".join(t for t, _ in rows)

    def body(self, rows):
        """The tree only. The hint line permanently contains the word "archived", so
        asserting over the whole screen would pass no matter what was drawn."""
        return "\n".join(t for t, a in rows if a is not None)

    def test_an_archived_subtree_is_one_row_and_its_agents_are_not_drawn(self):
        rows = board.layout(snap(agent("main"),
                                 agent("lead", depth=1, parent="main", archived=True),
                                 agent("w1", depth=2, parent="lead", archived=True)),
                            top=0, height=12, width=100, msg="")
        self.assertEqual([getattr(a, "name", "GROUP") for a in self.drawn(rows)],
                         ["main", "GROUP"])
        self.assertIn("+ 2 archived", self.text(rows))

    def test_a_click_on_a_collapsed_row_never_resolves_to_an_agent(self):
        """The misclick this whole file is about. `agent_at` hands back whatever the row
        carries, so a collapsed row that read as an agent would focus one — and which one
        depends on nothing the human can see."""
        rows = board.layout(snap(agent("main"),
                                 agent("a", depth=1, parent="main", archived=True),
                                 agent("b", depth=1, parent="main", archived=True)),
                            top=0, height=12, width=100, msg="")
        at = [(i + 1, a) for i, (_, a) in enumerate(rows) if a is not None]
        groups = [(r, a) for r, a in at if board._is_group(a)]
        self.assertEqual(len(groups), 1)
        row, got = groups[0]
        self.assertIs(board.agent_at(rows, row), got)
        self.assertIsInstance(got, status.Collapsed)
        self.assertFalse(hasattr(got, "name"))

    def test_a_live_agent_is_still_clickable_next_to_a_collapsed_group(self):
        rows = board.layout(snap(agent("main"),
                                 agent("live", depth=1, parent="main"),
                                 agent("dead", depth=1, parent="main", archived=True)),
                            top=0, height=12, width=100, msg="")
        named = [(i + 1, a.name) for i, (_, a) in enumerate(rows)
                 if a is not None and not board._is_group(a)]
        for row, name in named:
            self.assertEqual(board.agent_at(rows, row).name, name)

    def test_scrolling_is_an_offset_into_drawn_rows_not_into_agents(self):
        """`top` indexed `snap.agents` before, and the clamp was `len(agents) - capacity`.
        With 30 of 34 agents collapsed away there are 5 rows on screen, so a `top` of 4
        is already past the end — but in agent-space it clamps to 31 and the window fills
        with archived rows that collapse says must not be drawn at all.
        """
        agents = [agent("main")]
        agents += [agent(f"live{i}", depth=1, parent="main") for i in range(3)]
        agents += [agent("dead", depth=1, parent="main", archived=True)]
        agents += [agent(f"d{i}", depth=2, parent="dead", archived=True) for i in range(29)]
        height = board.CHROME + 6                       # capacity 3 rows, 5 to show

        rows = board.layout(snap(*agents), top=0, height=height, width=100, msg="")
        self.assertEqual([getattr(a, "name", "GROUP") for a in self.drawn(rows)],
                         ["main", "live0", "live1"])
        rows = board.layout(snap(*agents), top=9999, height=height, width=100, msg="")
        self.assertEqual([getattr(a, "name", "GROUP") for a in self.drawn(rows)],
                         ["live1", "live2", "GROUP"])
        # Nothing hidden by collapse can be reached by scrolling to it.
        for top in range(0, 40):
            got = self.drawn(board.layout(snap(*agents), top=top, height=height,
                                          width=100, msg=""))
            self.assertFalse([a for a in got if not board._is_group(a) and a.archived])

    def test_the_more_below_count_counts_rows_on_screen_not_agents(self):
        """A footer that contradicts the screen is worse than no footer: the human
        scrolls looking for thirty rows that were never going to be drawn."""
        agents = [agent(f"live{i}") for i in range(6)]
        agents += [agent("dead", archived=True)]
        agents += [agent(f"d{i}", depth=1, parent="dead", archived=True) for i in range(40)]
        # capacity = height - CHROME, in LINES; small enough that something is below.
        height = board.CHROME + 6
        rows = board.layout(snap(*agents), top=0, height=height, width=100, msg="")
        self.assertEqual(len(self.drawn(rows)), 3)
        self.assertIn("+4 more below", self.text(rows))      # 7 drawn rows, 3 shown

    def test_a_fleet_that_has_entirely_finished_still_draws(self):
        """Every root archived, so the window is one collapsed row and there is no agent
        left to size a column against. This is the ORDINARY end-of-session state, and
        `max()` over an empty sequence raises."""
        rows = board.layout(snap(agent("a", archived=True), agent("b", archived=True)),
                            top=0, height=12, width=100, msg="")
        self.assertIn("+ 2 archived", self.text(rows))
        self.assertEqual(len(rows), 12)

    def test_show_archived_draws_every_agent_again(self):
        s = snap(agent("main"), agent("gone", depth=1, parent="main", archived=True))
        rows = board.layout(s, top=0, height=12, width=100, msg="", show_archived=True)
        self.assertEqual([a.name for a in self.drawn(rows)], ["main", "gone"])
        self.assertNotIn("archived", self.body(rows))

    def test_a_herdr_outage_draws_the_whole_fleet_rather_than_one_row(self):
        """`alive is None`, so nothing is archived however old the rows are. A panel that
        collapsed the fleet on a subprocess hiccup would be worse than no panel."""
        unknown = [agent(f"a{i}", alive=None, herdr_state=None) for i in range(4)]
        for a in unknown:
            a.age = int(status.SPAWN_GRACE) + 1
        # Four rows and the three group breaks between them, off the chrome: the question
        # here is what `display_rows` keeps, so the pane is sized not to be the answer.
        rows = board.layout(snap(*unknown), top=0, height=board.CHROME + 7, width=100,
                            msg="")
        self.assertEqual([a.name for a in self.drawn(rows)], ["a0", "a1", "a2", "a3"])
        self.assertNotIn("archived", self.body(rows))

    def test_the_panel_and_sb_status_share_one_default(self):
        """Two renderings of one snapshot. If the panel kept its own default they could
        disagree about the same fleet on the same screen, and `display.show_archived`
        would be a setting that only half the product obeyed."""
        s = snap(agent("main"), agent("gone", depth=1, parent="main", archived=True))
        rows = board.layout(s, top=0, height=12, width=100, msg="")
        self.assertEqual([getattr(a, "name", "GROUP") for a in self.drawn(rows)],
                         ["main", "GROUP"])
        with mock.patch.object(status, "SHOW_ARCHIVED", True):
            rows = board.layout(s, top=0, height=12, width=100, msg="")
            self.assertEqual([a.name for a in self.drawn(rows)], ["main", "gone"])

    def test_the_header_still_counts_every_agent_a_collapse_hid(self):
        """Collapse shortens the tree, not the readout. Three agents, two rows — so a
        header that had quietly started counting rows would read "2 agents" here."""
        s = snap(agent("main"),
                 agent("d1", depth=1, parent="main", archived=True),
                 agent("d2", depth=1, parent="main", archived=True))
        rows = board.layout(s, top=0, height=12, width=200, msg="")
        self.assertEqual(len(self.drawn(rows)), 2)
        self.assertIn("3 agents", rows[0][0])
        self.assertIn(status.summary_line(s), board._ANSI.sub('', rows[0][0]))


class YouAreHereTest(unittest.TestCase):
    """Which row a board highlights: the agent sharing its own tmux tab.

    The mark itself is a background the renderer paints (`richboard._wash`) and the live
    proof is two boards on two tabs lighting two different rows — neither is testable here.
    What is pinned is the join, which is the part with no terminal in it: a `herdr pane
    list` payload and a tab id in, a set of sibling pane ids out (`tab_siblings`), and
    those against published rows to a name (`here_agent`).
    """

    # `herdr pane list`'s own shape, trimmed to the keys this reads — one tab holding an
    # agent pane and the board beside it, and a second tab of the same shape.
    PANES = [
        {"pane_id": "w1:p1", "tab_id": "w1:t1", "agent": "claude"},
        {"pane_id": "w1:p2", "tab_id": "w1:t1"},
        {"pane_id": "w1:p3", "tab_id": "w1:t2", "agent": "claude"},
        {"pane_id": "w1:p4", "tab_id": "w1:t2"},
    ]
    ROWS = [agent("alpha", pane_id="w1:p1"), agent("beta", pane_id="w1:p3")]

    def test_each_board_finds_the_agent_on_its_own_tab_and_not_the_other_one(self):
        """The whole feature in one assertion. Two boards, two tabs, two answers — if
        this ever returned the same name for both, every board in the fleet would be
        highlighting one agent and saying "you are here" to forty people at once."""
        first = board.tab_siblings(self.PANES, "w1:t1", "w1:p2")
        second = board.tab_siblings(self.PANES, "w1:t2", "w1:p4")
        self.assertEqual((first, second), (["w1:p1"], ["w1:p3"]))
        self.assertEqual(board.here_agent(self.ROWS, first), "alpha")
        self.assertEqual(board.here_agent(self.ROWS, second), "beta")

    def test_nothing_to_highlight_is_ordinary_and_never_an_error(self):
        """Four ways to have no answer, and all four are normal: a board outside herdr
        with no tab id at all, a single-pane tab, a tab whose only sibling belongs to no
        agent row (another checkout's fleet, or a hand-opened shell), and rows carrying no
        pane id because an older collector published them."""
        self.assertEqual(board.tab_siblings(self.PANES, None, "w1:p2"), [])
        self.assertEqual(board.tab_siblings(self.PANES, "w1:t9", None), [])
        self.assertIsNone(board.here_agent(self.ROWS, []))
        self.assertIsNone(board.here_agent(self.ROWS, ["w1:p99"]))
        self.assertIsNone(board.here_agent([agent("alpha")], ["w1:p1"]))

    def test_the_lookup_is_throttled_and_off_without_a_tab(self):
        """`herdr pane list` is a subprocess and the board redraws twice a second, so
        what is pinned is that ticking does not mean asking. `_resolve` is not run here —
        `tick` only ever starts the thread — so nothing shells out either way."""
        loc = board.Locator(refresh=10.0, env={"HERDR_TAB_ID": "w1:t1",
                                               "HERDR_PANE_ID": "w1:p2"})
        loc._busy = True                     # stand in for the worker, so none is started
        self.assertTrue(loc.enabled)
        self.assertFalse(loc.tick(at=1000.0))
        loc._busy = False
        self.assertTrue(loc.tick(at=1000.0))
        loc._busy = False
        self.assertFalse(loc.tick(at=1009.9))
        loc._busy = False
        self.assertTrue(loc.tick(at=1010.0))

        outside = board.Locator(env={})      # a bare `python -m switchboard.board`
        self.assertFalse(outside.enabled)
        self.assertFalse(outside.tick(at=1000.0))
        self.assertIsNone(outside.name(self.ROWS))


HOOK_PY = """
def board_lines(state_dir, workspace, rows):
    return [f"{workspace}: {len(rows)} rows"]
"""

MARK_PY = """
import os
open(os.environ["PR8_MARK"], "a").write("imported\\n")
API = 1
VERSION = "0"
def register(reg):
    pass
"""


def a_plugin(root: Path, name: str, *, draws: bool = True, hook: str = HOOK_PY) -> Path:
    """A plugin on disk, with or without the `board.py` the seam looks for."""
    d = root / name
    d.mkdir(parents=True)
    (d / "__init__.py").write_text(MARK_PY)
    if draws:
        (d / "board.py").write_text(hook)
    return d


def a_plugin_repo(tmp: Path, *, enabled: str, plugins: dict) -> Path:
    """A checkout with a `.git` directory, an enablement file, and plugins of its own.

    A plain directory rather than a real repo, because `panel.git_common_dir` resolves
    `.git` in Python and never spawns anything — which is exactly the property the seam
    leans on. `SeamPathsTest` is where a real checkout is used, to pin this against the
    path `switchboard.plugins` would have computed.

    `enabled` APPENDS to the shipped `defaults/plugins.toml`, so a test that asserts an
    exact set of asked plugins has to start its list with `"!reset"` — otherwise whatever
    ships enabled and ships a `board.py` (today `plans`) is legitimately asked too, and
    the assertion is about the shipped defaults rather than about the seam.
    """
    repo = tmp / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".switchboard").mkdir()
    (repo / ".switchboard" / "plugins.toml").write_text(f"enabled = {enabled}\n")
    for name, kw in plugins.items():
        a_plugin(repo / ".switchboard" / "plugins", name, **kw)
    return repo


class PluginSeamTest(unittest.TestCase):
    """The board's one extension point: is it generic, and is it free when nothing uses it?

    Both halves matter and the second one more. The seam is on the path of every frame of
    every board in every repo — `report-bug` and `suggestions` ship enabled — so "a plugin
    that draws nothing costs nothing" has to be a fact about what the code does, not a
    hope. What is pinned here is that a plugin which is disabled, or which ships no
    `board.py`, is NEVER IMPORTED: proved by a plugin whose `__init__.py` writes a file
    when it runs.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.mark = self.tmp / "imported"
        patch = mock.patch.dict(os.environ, {"PR8_MARK": str(self.mark)})
        patch.start()
        self.addCleanup(patch.stop)
        board._HOOKS.clear()
        self.addCleanup(board._HOOKS.clear)
        for name in [m for m in sys.modules if m.startswith(board._MODULE_PREFIX)]:
            del sys.modules[name]

    def test_a_disabled_plugin_is_not_asked_and_is_never_imported(self):
        """`enabled` is read out of config — files, no subprocess — and a name that is not
        in it never reaches an import. The board a repo has today is the board it keeps."""
        repo = a_plugin_repo(self.tmp, enabled='["!reset"]', plugins={"drawer": {}})
        self.assertEqual(board.board_hooks(repo), [])
        self.assertFalse(self.mark.exists())

    def test_a_plugin_that_ships_no_board_file_is_never_imported(self):
        """The whole cost of an enabled plugin that draws nothing: one `is_file`. This is
        every plugin that ships today, so it is the ordinary case and not the corner."""
        repo = a_plugin_repo(self.tmp, enabled='["!reset", "quiet"]',
                             plugins={"quiet": {"draws": False}})
        self.assertEqual(board.board_hooks(repo), [])
        self.assertFalse(self.mark.exists())

    def test_an_enabled_plugin_that_draws_is_asked_for_each_worktree_group(self):
        """The seam itself, and nothing about plans: board.py knows only that something
        was enabled and had lines for a group."""
        repo = a_plugin_repo(self.tmp, enabled='["!reset", "drawer"]', plugins={"drawer": {}})
        hooks = board.board_hooks(repo)
        self.assertEqual([n for n, _, _, _ in hooks], ["drawer"])
        self.assertTrue(self.mark.exists())
        rows = [agent("a"), agent("b", depth=1, parent="a"),
                agent("c", workspace="web")]
        with mock.patch.object(board, "board_hooks", return_value=hooks):
            self.assertEqual(board.group_extras(rows),
                             [[], ["api: 2 rows"], ["web: 1 rows"]])

    def test_a_plugin_that_breaks_costs_the_board_nothing(self):
        """Four ways to be wrong — raising at import, raising when asked, answering with
        something that is not a list of lines — and all four are silence. A board is what
        a human looks at to find out something has gone wrong; it must not be the thing."""
        for body in ("raise RuntimeError('boom')\n",
                     "def board_lines(*a):\n    raise RuntimeError('boom')\n",
                     "def board_lines(*a):\n    return 'not a list'\n",
                     "board_lines = 3\n"):
            with self.subTest(body=body.splitlines()[0]):
                board._HOOKS.clear()
                tmp = Path(tempfile.mkdtemp())
                self.addCleanup(shutil.rmtree, tmp, True)
                repo = a_plugin_repo(tmp, enabled='["!reset", "drawer"]',
                                     plugins={"drawer": {"hook": body}})
                hooks = board.board_hooks(repo)
                with mock.patch.object(board, "board_hooks", return_value=hooks):
                    self.assertEqual(board.group_extras([agent("a")]), [[]])

    def test_a_line_with_a_newline_in_it_becomes_two_lines_and_never_wraps(self):
        """One line is one row here. A plugin that put a newline in a string is describing
        two rows however it meant it, and a string that wraps moves every row below it."""
        hook = "def board_lines(*a):\n    return ['one\\ntwo', 'three']\n"
        repo = a_plugin_repo(self.tmp, enabled='["!reset", "drawer"]',
                             plugins={"drawer": {"hook": hook}})
        with mock.patch.object(board, "board_hooks",
                               return_value=board.board_hooks(repo)):
            self.assertEqual(board.group_extras([agent("a")])[0],
                             ["one", "two", "three"])

    def test_a_drawers_control_characters_never_reach_the_terminal(self):
        """The guard the docstring promises, kept by the BOARD and not by the plugin.

        The seam is a generic extension point, so the manners of code nobody in this repo
        wrote are not a guarantee. Two characters and two different disasters: `ESC [ 2J`
        is not SGR, so `_ANSI` never sees it and `_fit` hands it to the terminal, which
        clears the pane; a TAB measures 0 to `_visible_len` and 8 to the terminal, so a
        line that fits wraps — and a wrap moves every row below it and misaims the next
        click. Each becomes one space, which is the only substitution that leaves the
        column count the plugin lined up on honest.
        """
        hook = ("def board_lines(*a):\n"
                "    return ['\\x1b[2J\\x1b[Hgotcha', 'a\\tb', 'bell\\x07', 'nel\\x85x']\n")
        repo = a_plugin_repo(self.tmp, enabled='["!reset", "drawer"]',
                             plugins={"drawer": {"hook": hook}})
        rows = [agent("solo")]
        with mock.patch.object(board, "board_hooks",
                               return_value=board.board_hooks(repo)):
            block = board.group_extras(rows)[0]
            drawn = [t for t, _ in board.layout(snap(*rows), top=0, height=14,
                                                width=100, msg="")]
            rich = [str(t) for t, _ in richboard.layout(snap(*rows), top=0, height=14,
                                                        width=100, msg="")] \
                if HAVE_RICH else []
        # `nel` splits rather than becoming a space: NEL is a line break to
        # `str.splitlines`, and one line is one row here — the same rule as a newline.
        self.assertEqual(block, [" [2J [Hgotcha", "a b", "bell ", "nel", "x"])
        for line in drawn + rich:
            self.assertNotIn("\x1b[2J", line)
            self.assertNotIn("\t", line)
            self.assertNotIn("\x07", line)

    def test_a_workspace_split_into_two_runs_is_drawn_once(self):
        """`group_runs` brackets CONSECUTIVE rows, and one workspace can hold two runs — a
        lead that delegated one child elsewhere and kept another at home. Asked per run,
        that workspace said the same thing twice and paid the drawer twice for it."""
        repo = a_plugin_repo(self.tmp, enabled='["!reset", "drawer"]', plugins={"drawer": {}})
        rows = [agent("lead"), agent("away", depth=1, parent="lead", workspace="web"),
                agent("home", depth=1, parent="lead")]
        with mock.patch.object(board, "board_hooks",
                               return_value=board.board_hooks(repo)):
            extras = board.group_extras(rows)
        # Once, under the LAST row of the workspace — and the drawer was handed every row
        # of it, both runs, rather than one run's worth.
        self.assertEqual(extras, [[], ["web: 1 rows"], ["api: 2 rows"]])

    def test_a_runaway_plugin_is_cut_off(self):
        hook = "def board_lines(*a):\n    return [str(i) for i in range(500)]\n"
        repo = a_plugin_repo(self.tmp, enabled='["!reset", "drawer"]',
                             plugins={"drawer": {"hook": hook}})
        with mock.patch.object(board, "board_hooks",
                               return_value=board.board_hooks(repo)):
            self.assertEqual(len(board.group_extras([agent("a")])[0]), board.HOOK_LINES)


class SeamOffIsTodaysBoardTest(unittest.TestCase):
    """The hard requirement: with nothing drawing, both renderers draw what they drew.

    Said as an equality rather than as a golden file, in the two places a difference could
    come from. `group_extras` returns one empty list per row, so the `costs` the window
    math is built on are the `2 if brk else 1` they always were; and the frame is line for
    line and owner for owner the frame drawn with the seam short-circuited entirely.
    """

    SNAP = None

    def setUp(self):
        board._HOOKS.clear()
        self.addCleanup(board._HOOKS.clear)
        self.snap = snap(agent("top"), agent("kid", depth=1, parent="top"),
                         agent("other", workspace="web"))

    def test_no_row_costs_more_than_it_did(self):
        with mock.patch.object(board, "board_hooks", return_value=[]):
            rows = status.display_rows(self.snap.agents, show_archived=False)
            self.assertEqual(board.group_extras(rows), [[] for _ in rows])

    def test_both_renderers_draw_the_frame_they_drew_before_the_seam(self):
        kw = dict(top=0, height=24, width=100, msg="", show_archived=False)
        with mock.patch.object(board, "board_hooks", return_value=[]):
            plain_off = board.layout(self.snap, **kw)
            rich_off = richboard.layout(self.snap, **kw)
        # The seam removed rather than merely quiet: `group_extras` never consulted, which
        # is the shape of this code before PR8 existed.
        with mock.patch.object(board, "group_extras",
                               side_effect=lambda rows: [[] for _ in rows]) as never:
            plain_none = board.layout(self.snap, **kw)
            rich_none = richboard.layout(self.snap, **kw)
        self.assertTrue(never.called)
        self.assertEqual(plain_off, plain_none)
        if HAVE_RICH:
            self.assertEqual([str(t) for t, _ in rich_off],
                             [str(t) for t, _ in rich_none])
            self.assertEqual([o for _, o in rich_off], [o for _, o in rich_none])


class PlanBlockTest(unittest.TestCase):
    """The plans plugin, drawn as its own section, in both renderers.

    The end of the wire and the only test here that knows what a plan is. It runs the
    SHIPPED plugin against a real `plans.json`, so what it pins is the whole path: the
    board finds `defaults/plugins/plans/board.py`, reads the `SECTION` on it, hands it the
    rows of each group, and draws the header and flowchart it gets back under one heading.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        board._HOOKS.clear()
        self.addCleanup(board._HOOKS.clear)
        self.repo = self.tmp / "repo"
        (self.repo / ".git").mkdir(parents=True)
        (self.repo / ".switchboard").mkdir()
        (self.repo / ".switchboard" / "plugins.toml").write_text('enabled = ["plans"]\n')
        self.state = self.repo / ".git" / "agentflow" / "plugins" / "plans"
        self.state.mkdir(parents=True)

    def write(self, *plans):
        (self.state / "plans.json").write_text(json.dumps(
            {"format": 1, "next_plan": 9, "next_step": 9, "plans": list(plans)}))

    def plan(self, pid, workspace, title, steps, checkout=None):
        return {"id": pid, "title": title, "workspace": workspace,
                "checkout": str(self.repo if checkout is None else checkout),
                "created_at": 0, "created_by": "lead", "changelog": [], "notes": [],
                "steps": steps}

    def hooks(self):
        h = board.board_hooks(self.repo)
        self.assertEqual([n for n, _, _, _ in h], ["plans"], "the shipped plans plugin")
        return mock.patch.object(board, "board_hooks", return_value=h)

    def test_plans_are_a_section_under_the_tree_in_both_renderers(self):
        """WHERE the plugin's lines go, which is the whole of what `SECTION` changes.

        Under the AGENTS tree and not under the worktree group they came from, with a
        heading of its own and one blank line above it — the same shape `STATS` has. Both
        renderers, because a section drawn in one and a hanging block in the other would
        be two boards showing one fleet differently.
        """
        self.write(self.plan("p-1", "api", "guardrails",
                             [{"id": "s-1", "name": "design", "progress": "done"},
                              {"id": "s-2", "name": "build it", "progress": "open",
                               "deps": ["s-1"]}]),
                   self.plan("p-2", "web", "the other one",
                             [{"id": "s-3", "name": "ship", "progress": "open"}]))
        rows = [agent("lead"), agent("kid", depth=1, parent="lead"),
                agent("web-1", workspace="web")]
        s = snap(*rows)
        with self.hooks():
            # Nothing hangs under a group any more: a section-drawing plugin is skipped
            # there, or the same plan would be on the screen twice.
            self.assertEqual(board.group_extras(rows), [[] for _ in rows])
            sections = board.section_extras(rows)
            plain = [t for t, _ in board.layout(s, top=0, height=24, width=110, msg="")]
            rich = [str(t) for t, _ in richboard.layout(
                s, top=0, height=24, width=110, msg="")] if HAVE_RICH else None
        self.assertEqual([title for title, _ in sections], ["PLANS"])
        # Every workspace on screen, in screen order, in ONE block.
        self.assertIn("guardrails", sections[0][1][0])
        self.assertIn("the other one", " ".join(sections[0][1]))
        for lines in ([plain, rich] if HAVE_RICH else [plain]):
            # Stripped of colour and of the panel's border, so one set of assertions can
            # ask both renderers the same question about where the section sits.
            body = [board._ANSI.sub("", x).strip(" │╭╮╰╯─") for x in lines]
            head = next(i for i, x in enumerate(body) if x.startswith("PLANS"))
            self.assertEqual(body[head - 1], "", "one blank line above it")
            # Below every agent row, which is what "after agents" means.
            self.assertGreater(head, max(i for i, x in enumerate(body)
                                         if "web-1" in x or "kid" in x))
            self.assertIn("guardrails", body[head + 1])
            self.assertIn("design", body[head + 2])
            # Names and arrows, and no step ids anywhere: progress is colour now.
            self.assertIn("→", body[head + 2])
            self.assertNotIn("s-1", " ".join(body))
            self.assertNotIn("s-2", " ".join(body))

    def test_a_plans_condition_is_read_off_the_rows_the_board_already_has(self):
        """The rule the design turns on: liveness is read off the agent rows and never
        copied onto the plan. The chart shows no owners, so the CONDITION is where that
        reading now surfaces — and it is the one a human scans for.

        Three answers and the difference between them is the point. A worktree somebody
        is working on is `live`; one whose every agent is closed is `dormant`; and a
        worktree that is GONE with steps still open is `abandoned`. None of it is stored.
        """
        def step(n):
            return [{"id": f"s-{n}", "name": "build", "progress": "open", "owner": "kid"}]
        self.write(self.plan("p-1", "api", "guardrails", step(1)),
                   self.plan("p-2", "web", "asleep", step(2), checkout=str(self.repo)),
                   self.plan("p-3", "vanished", "gone away", step(3),
                             checkout=str(self.repo / "not-a-checkout")))
        rows = [agent("lead"),
                agent("kid", depth=1, parent="lead", state="blocked",
                      blocked_why="waiting"),
                agent("web-1", workspace="web", state="done", gone=True),
                agent("ghost", workspace="vanished", state="done", gone=True)]
        with self.hooks():
            lines = board.section_extras(rows)[0][1]
        by_plan = {x.split()[0]: board._ANSI.sub("", x)
                   for x in lines if x.split() and x.split()[0].startswith("p-")}
        self.assertIn("live", by_plan["p-1"])
        self.assertIn("dormant", by_plan["p-2"])
        self.assertIn("abandoned", by_plan["p-3"])

    def test_a_plan_whose_agents_were_all_archived_reads_dormant_and_not_live(self):
        """The board and `show` must not disagree about one plan, and this is where they did.

        `sb cleanup` is the ordinary end of a job: every agent on the worktree is archived
        and the tree collapses them into one `+ N archived` row. That row carries no agent,
        so dropping it left the board with no agents for the workspace at all — which
        `condition` reads as "nobody was ever here" and answers `live`, while `list`/`show`
        ask `sb status`, see the archived rows themselves, and say `dormant`.

        Built through the REAL `display_rows`, so what is pinned is the collapse the board
        actually gets rather than a hand-made row, and asserted against the same fleet drawn
        uncollapsed: one answer, whichever way the tree is being shown.
        """
        self.write(self.plan("p-1", "api", "guardrails",
                             [{"id": "s-1", "name": "build", "progress": "open"}]))
        fleet = [agent("lead", workspace="home"),
                 agent("kid", depth=1, parent="lead", state="done", archived=True)]
        collapsed = status.display_rows(fleet, show_archived=False)
        self.assertTrue(any(isinstance(r, status.Collapsed) for r in collapsed),
                        "the cleaned-up subtree is one collapsed row")
        with self.hooks():
            hidden = board.section_extras(collapsed)[0][1]
            shown = board.section_extras(
                status.display_rows(fleet, show_archived=True))[0][1]
        self.assertIn("dormant", board._ANSI.sub("", hidden[0]))
        self.assertNotIn("live", board._ANSI.sub("", hidden[0]))
        # The same fleet with the archived rows drawn one by one — which is what `show`
        # sees — already read dormant, and is what the collapsed answer must match.
        self.assertEqual(board._ANSI.sub("", hidden[0]), board._ANSI.sub("", shown[0]))

    def test_a_wide_display_name_is_measured_in_columns_and_not_in_characters(self):
        """A CJK name is drawn twice as wide as it is counted, unless it is counted right.

        The core fixed this once for its own rows (`_visible_len`: "measuring in characters
        is the bug this whole section exists to close") and the chart pads and clips by the
        same measure. What breaks otherwise is the chart's own alignment: the column is
        padded to four when the name occupies eight, and every connector in the gap lands
        four columns left of the name it leaves.
        """
        self.write(self.plan("p-1", "api", "shape", [
            {"id": "s-1", "name": "scope", "display": "检查代码", "progress": "open"},
            {"id": "s-2", "name": "build", "progress": "open", "deps": ["s-1"]},
            {"id": "s-3", "name": "ccc", "progress": "open", "deps": ["s-1"]}]))
        with self.hooks():
            lines = [board._ANSI.sub("", x)
                     for x in board.section_extras([agent("lead")])[0][1]]
        arrows = [board._visible_len(x.split("→")[0]) for x in lines[1:]]
        self.assertEqual(arrows[0], arrows[1],
                         f"the fan-out arrives at one column: {lines[1:]!r}")
        # Eight columns of name and the air after it, not four — the block's own indent
        # and the cell's leading space are the other two.
        self.assertEqual(board._visible_len(lines[1].split("─")[0]), 11)

    def test_a_name_too_wide_for_a_cell_is_clipped_to_columns(self):
        """The clip is 22 COLUMNS. Counted in characters it let 44 through.

        21 and not 22, and that is `_clip_cols`'s own rule rather than an off-by-one: the
        next ideograph is two columns wide and only one is left, so it comes up short by
        one rather than over by one. Short is a cosmetic gap; over is what this fixes.
        """
        self.write(self.plan("p-1", "api", "shape",
                             [{"id": "s-1", "name": "x", "display": "检" * 30,
                               "progress": "open"}]))
        with self.hooks():
            lines = [board._ANSI.sub("", x)
                     for x in board.section_extras([agent("lead")])[0][1]]
        self.assertEqual(board._visible_len(lines[1].strip()), 21)
        self.assertTrue(lines[1].rstrip().endswith("…"))

    def test_a_dep_written_as_a_bare_number_is_the_edge_show_says_it_is(self):
        """Ids compare as NUMBERS everywhere else in the plugin, and now here too.

        `plans.json` is hand-edited by a lead, `_check` accepts a bare `1` in `deps`, and
        `show` renders it as `after 1` — so a board matching the strings drew no edge for
        exactly the dep a hand-edit is most likely to write. The same slip let a self-dep
        written as `1` past the guard and out as an arrow into nothing.
        """
        self.write(self.plan("p-1", "api", "shape", [
            {"id": "s-1", "name": "scope", "progress": "open"},
            {"id": "s-2", "name": "build", "progress": "open", "deps": ["1"]}]),
                   self.plan("p-2", "api", "loop", [
                       {"id": "s-3", "name": "alone", "progress": "open", "deps": ["3"]}]))
        with self.hooks():
            lines = [board._ANSI.sub("", x).rstrip()
                     for x in board.section_extras([agent("lead")])[0][1]]
        self.assertEqual(lines[1], "  scope ───→ build")
        # And a step depending on ITSELF by number is still no edge at all.
        self.assertEqual(lines[3], "  alone")

    def test_a_plans_steps_are_drawn_as_the_graph_they_are(self):
        """`after s-1, s-2` is a DAG spelled out in words. The board draws the DAG.

        A diamond, which is the shape that catches a router that only knows chains: two
        steps that both wait on the first and are both waited on by the last. What must
        come out is one line per row, names in dependency order left to right, and the
        two branches closing back onto the last step.
        """
        self.write(self.plan("p-1", "api", "shape", [
            {"id": "s-1", "name": "scope", "progress": "open"},
            {"id": "s-2", "name": "build", "progress": "open", "deps": ["s-1"]},
            {"id": "s-3", "name": "docs", "progress": "open", "deps": ["s-1"]},
            {"id": "s-4", "name": "ship", "progress": "open", "deps": ["s-2", "s-3"]}]))
        with self.hooks():
            lines = [board._ANSI.sub("", x)
                     for x in board.section_extras([agent("lead")])[0][1]]
        self.assertEqual([x.rstrip() for x in lines[1:]],
                         ["  scope ──┬→ build ──┬→ ship",
                          "          └→ docs  ──┘"])

    def test_a_step_draws_its_display_name_and_falls_back_to_its_full_name(self):
        """The short board label a step carries, or its name where it has none.

        A cell in a flowchart is a few columns and a full step name is a sentence, so a step
        authored with a `display` draws that and a step without one falls back to its `name`.
        Both on one chart, so what is pinned is the choice per step and not a mode.
        """
        self.write(self.plan("p-1", "api", "shape", [
            {"id": "s-1", "name": "list every claim the document makes",
             "display": "list claims", "progress": "open"},
            {"id": "s-2", "name": "ship", "progress": "open", "deps": ["s-1"]}]))
        with self.hooks():
            lines = [board._ANSI.sub("", x)
                     for x in board.section_extras([agent("lead")])[0][1]]
        chart = " ".join(x.strip() for x in lines[1:])
        self.assertIn("list claims", chart, "the display name is drawn")
        self.assertNotIn("list every claim", chart, "and never the long name behind it")
        self.assertIn("ship", chart, "a step with no display name falls back to its name")

    def test_progress_is_colour_and_the_seam_carries_it(self):
        """The other half of the drawing: no progress column, and colour instead.

        Which is a claim about the SEAM as much as about the plugin — `_colour_only` has
        to let SGR through while still flattening everything else, or the plugin's colours
        arrive as literal escape characters in the middle of a line.
        """
        self.write(self.plan("p-1", "api", "shape", [
            {"id": "s-1", "name": "scope", "progress": "skipped"},
            {"id": "s-2", "name": "build", "progress": "done", "deps": ["s-1"]},
            {"id": "s-3", "name": "ship", "progress": "open", "deps": ["s-2"]}]))
        with self.hooks():
            chart = board.section_extras([agent("lead")])[0][1][1]
        self.assertNotIn("skipped", chart)
        self.assertNotIn("done", chart)
        self.assertIn("\033[32mbuild\033[0m", chart, "done is green")
        self.assertIn("\033[90mscope\033[0m", chart, "skipped is grey")
        self.assertIn(" ship", board._ANSI.sub("", chart), "open is left unpainted")
        self.assertTrue(chart.endswith("\033[0m"), "and never leaks past its own line")

    def test_a_plugin_may_colour_a_word_and_still_may_not_move_the_cursor(self):
        """The seam's rule, now that it is two rules. SGR through, everything else flat —
        `ESC [ 2J` clears the pane and `ESC [ H` moves the cursor, and neither is SGR."""
        got = board._colour_only("\033[31mred\033[0m\033[2Jwiped\033[Hhome\ttab")
        self.assertIn("\033[31mred", got)
        self.assertNotIn("\033[2J", got)
        self.assertNotIn("\033[H", got)
        # The ESC becomes a space and the rest of the sequence is left as the harmless
        # text it now is — one character out for one character in, which is what keeps a
        # plugin's own alignment honest. See `_hook_lines`.
        self.assertEqual(board._ANSI.sub("", got), "red [2Jwiped [Hhome tab")
        self.assertNotIn("\t", got)

    def test_a_plan_created_after_the_board_opened_appears_on_the_next_frame(self):
        """THE ORDINARY FIRST USE, and the one this could most easily get wrong.

        A plugin's state directory is made by its first COMMAND, not by the board. So the
        normal sequence is: Andrew opens the board with no plan anywhere, a lead runs
        `sb plugin plans create`, and the plan must appear. A discovery pass that took
        "no state directory" as "nothing to draw" and cached it for the life of the pane
        would never show it, and nothing on screen would say why. Here the directory does
        not exist for the first frame at all.
        """
        shutil.rmtree(self.state)
        hooks = board.board_hooks(self.repo)
        self.assertEqual([n for n, _, _, _ in hooks], ["plans"])
        rows = [agent("lead")]
        with mock.patch.object(board, "board_hooks", return_value=hooks):
            self.assertEqual(board.section_extras(rows), [])      # nothing yet, no error
            self.state.mkdir(parents=True)                       # `plans create` happens
            self.write(self.plan("p-1", "api", "guardrails",
                                 [{"id": "s-1", "name": "build", "progress": "open"}]))
            self.assertIn("guardrails", board.section_extras(rows)[0][1][0])

    def test_drawing_a_plan_shells_out_to_nothing(self):
        """`list` and `show` build a `_Live` and spend seconds of `sb status` on it. A
        board redraws every couple of seconds, per group, and must not — which is the
        whole reason the rows are handed in. Pinned by making `subprocess.run` explode."""
        self.write(self.plan("p-1", "api", "guardrails", [
            {"id": "s-1", "name": "build", "progress": "open", "owner": "lead"}]))
        with self.hooks(), mock.patch(
                "subprocess.run", side_effect=AssertionError("the board shelled out")):
            block = board.section_extras([agent("lead")])[0][1]
        self.assertIn("guardrails", block[0])

    def test_a_plan_on_another_worktree_is_drawn_by_nobody(self):
        self.write(self.plan("p-1", "somewhere-else", "not here",
                             [{"id": "s-1", "name": "x", "progress": "open"}]))
        with self.hooks():
            self.assertEqual(board.section_extras([agent("lead")]), [])

    def test_a_plans_file_that_cannot_be_read_costs_the_board_nothing(self):
        (self.state / "plans.json").write_text("{ not json")
        with self.hooks():
            self.assertEqual(board.section_extras([agent("lead")]), [])


class SeamWindowTest(unittest.TestCase):
    """Variable-height blocks and the window arithmetic, which is where this could hurt.

    A block is lines, and every renderer counts lines: the plain board charges them into
    `costs`, and `richboard._window`, which was written when a row was exactly one line,
    now takes the same list. What must never happen is a frame taller than the pane —
    a line over the edge pushes nothing off screen, it wraps, and the next click focuses
    the wrong agent.
    """

    def tall(self, n):
        return mock.patch.object(
            board, "group_extras",
            side_effect=lambda rows: [[f"plan line {i}" for i in range(n)]
                                      if r is rows[-1] else [] for r in rows])

    def test_neither_renderer_ever_draws_past_the_bottom_of_the_pane(self):
        """SCROLLED TOPS TOO, and `rich` is required to draw rather than allowed to
        decline. `richboard.layout` returns None for a frame whose line count did not come
        back the way it was built, which is a legitimate fallback and also exactly what a
        window-math regression looks like — so a block that broke the arithmetic would
        pass this sweep as "not drawn" if None were tolerated. At these sizes it draws.

        Where `rich` is not installed there is no rich renderer to hold to that, and the
        plain half of the sweep is the whole test — see `HAVE_RICH` at the top of the
        file."""
        s = snap(*[agent(f"a{i}", depth=i % 2, parent="a0" if i % 2 else None,
                         workspace=["api", "web", "db"][i % 3])
                   for i in range(6)])
        for height in range(6, 30):
            for n in (0, 1, 5, 40):
                for top in (0, 1, 3, 7):
                    with self.subTest(height=height, block=n, top=top), self.tall(n):
                        plain = board.layout(s, top=top, height=height, width=100, msg="")
                        self.assertEqual(len(plain), height)
                        if HAVE_RICH:
                            rich = richboard.layout(s, top=top, height=height, width=100,
                                                    msg="")
                            self.assertIsNotNone(rich)
                            self.assertEqual(len(rich), height)

    def deep(self, n):
        """A plugin section `n` lines tall, on top of whatever else the pane holds."""
        return mock.patch.object(
            board, "section_extras",
            return_value=[("PLANS", [f"plan line {i}" for i in range(n)])] if n else [])

    def test_a_section_never_pushes_the_frame_past_the_bottom_of_the_pane(self):
        """The same sweep for the other placement, which has its own arithmetic.

        A section is sized before the tree is windowed and is the FIRST thing to give its
        lines back, so the two things that could go wrong are opposite: a frame taller
        than the pane, and a board that spent its last line on a heading instead of an
        agent. Both are checked here, at every height a pane can be.

        Where `rich` is not installed the plain half is the whole test, exactly as in the
        sweep above — see `HAVE_RICH` at the top of the file.
        """
        s = snap(*[agent(f"a{i}", depth=i % 2, parent="a0" if i % 2 else None,
                         workspace=["api", "web"][i % 2]) for i in range(4)])
        for height in range(6, 30):
            for n in (0, 1, 5, 40):
                for top in (0, 3):
                    with self.subTest(height=height, section=n, top=top), self.deep(n):
                        plain = board.layout(s, top=top, height=height, width=100, msg="")
                        self.assertEqual(len(plain), height)
                        frames = [[t for t, _ in plain]]
                        if HAVE_RICH:
                            rich = richboard.layout(s, top=top, height=height, width=100,
                                                    msg="")
                            self.assertIsNotNone(rich)
                            self.assertEqual(len(rich), height)
                            frames.append([str(t) for t, _ in rich])
                        # The tree outranks the section, always and in every renderer.
                        for lines in frames:
                            body = " ".join(lines)
                            self.assertTrue(any(f"a{i}" in body for i in range(4)),
                                            "an agent row survived")

    def test_the_agent_row_outranks_its_own_block(self):
        """A plan tall enough to fill a pane must not push the agent it hangs off it."""
        s = snap(agent("solo"))
        with self.tall(50):
            body = [board._ANSI.sub("", t) for t, _ in
                    board.layout(s, top=0, height=12, width=80, msg="")]
        self.assertTrue(any("solo" in x for x in body))
        self.assertTrue(any("plan line 0" in x for x in body))

    def test_scrolling_counts_the_block_lines_and_not_just_the_rows(self):
        """`_max_top` is in LINES. With five lines hanging off the last row, the last
        screenful starts higher up than it would with rows alone — and a board that
        scrolled past that would claim rows were on screen that are not."""
        rows = [agent(f"a{i}", depth=1, parent="a0") for i in range(8)]
        rows[0] = agent("a0")
        plain = [2 if b else 1 for b in
                 [board._starts_group(rows, i) for i in range(len(rows))]]
        with_block = list(plain)
        with_block[-1] += 5
        self.assertLess(board._max_top(plain, 10), board._max_top(with_block, 10))

    def test_the_rich_window_is_unchanged_when_every_row_is_one_line(self):
        """`_window` grew a `costs` argument; with `None`, or with a list of ones, it must
        answer exactly what it answered before — every scroll position, every room."""
        for n in range(0, 9):
            for room in range(0, 12):
                for top in range(0, 10):
                    with self.subTest(n=n, room=room, top=top):
                        self.assertEqual(richboard._window(n, top, room),
                                         richboard._window(n, top, room, [1] * n))

    def test_the_rich_window_never_hands_back_more_lines_than_the_room(self):
        costs = [1, 1, 4, 1, 6, 1]
        for room in range(1, 16):
            for top in range(0, 6):
                first, last = richboard._window(len(costs), top, room, costs)
                if first == last:
                    continue        # no row fits at all; `layout` gives head lines back
                spent = sum(costs[first:last]) + (1 if first else 0) \
                    + (1 if last < len(costs) else 0)
                with self.subTest(room=room, top=top):
                    self.assertLessEqual(spent, room)


class SeamPathsTest(unittest.TestCase):
    """The two paths `board.py` resolves itself, pinned against the module that owns them.

    `switchboard.plugins` imports `store`, and a renderer may not — `tests/test_panel.py`
    is that guarantee and `report-bug` and `suggestions` ship enabled, so the seam runs in
    every repo and cannot reach for it. So the board globs the plugin roots itself and
    computes the state directory itself, and these two tests are what stop the copies
    drifting from the originals.
    """

    def test_the_board_finds_exactly_the_plugins_that_plugins_available_finds(self):
        from switchboard import plugins
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        repo = a_plugin_repo(tmp, enabled='["!reset", "own", "plans"]',
                             plugins={"own": {}, "notaplugin": {}})
        (repo / ".switchboard" / "plugins" / "notaplugin" / "__init__.py").unlink()
        (repo / ".switchboard" / "plugins" / "a-preset.md").write_text("not a plugin")
        # `plans` is shipped and not the repo's, and it has a state directory here, so it
        # is found through the OTHER root — which is the half a one-root glob would miss.
        (repo / ".git" / "agentflow" / "plugins" / "plans").mkdir(parents=True)
        board._HOOKS.clear()
        self.addCleanup(board._HOOKS.clear)
        with mock.patch.dict(os.environ, {"PR8_MARK": str(tmp / "m")}):
            found = {n for n, _, _, _ in board.board_hooks(repo)}
        self.assertLessEqual(found, set(plugins.available(repo)))
        self.assertEqual(found, {"own", "plans"})

    def test_drawing_a_plugins_lines_does_not_hand_the_board_a_database(self):
        """`RendererImports` in `tests/test_panel.py` proves the renderer MODULES cannot
        reach `store`. This is the half PR8 added and could have broken: the board now
        imports plugin packages, and a plugin imports `switchboard.plugins` for `Result`,
        so a `store` at the top of that module would have put `store.connect` two
        attribute lookups from the process drawing Andrew's board. A fresh interpreter,
        because this one has imported the store to run the rest of the file."""
        out = subprocess.run(
            [sys.executable, "-c",
             "import switchboard.plugins, sys; "
             "print('switchboard.store' in sys.modules)"],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.strip(), "False")

    def test_the_state_directory_is_the_one_the_plugin_itself_would_write_to(self):
        """Two spellings of one path — `plugins.state_root` goes through
        `store.repo_root()`, which spawns `git`, and the board goes through
        `panel.git_common_dir`, which does not. A real checkout, because that is the only
        way to ask the first one at all."""
        from switchboard import plugins
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        repo = tmp / "repo"
        repo.mkdir()
        for cmd in (["init", "-q", "-b", "main"],
                    ["-c", "user.email=t@t", "-c", "user.name=t",
                     "commit", "-q", "--allow-empty", "-m", "x"]):
            subprocess.run(["git", *cmd], cwd=repo, check=True,
                           capture_output=True)
        want = plugins.state_root("repo", repo) / "plans"
        want.mkdir(parents=True)
        self.assertEqual(board._state_dir(repo, "plans", "repo"), want)
        # Named whether or not it is there, and never created: a plugin's directory is
        # made by its first command, and a board that refused the hook until then would
        # never show the first plan. `_read` answers an empty document for a missing file.
        never = want.parent / "never-run"
        self.assertEqual(board._state_dir(repo, "never-run", "repo"), never)
        self.assertFalse(never.exists())
        # No repo, no path to name.
        self.assertIsNone(board._state_dir(tmp / "not-a-repo", "plans", "repo"))


class ReportFilesTest(unittest.TestCase):
    """What double-`o` opens, from prose that also cites code it merely read.

    The strings below are real assistant text shapes taken off transcripts in this
    repo — the "wrote it to X" one, which is the whole point of the feature, and the
    "`board.py:1914-1929`" citation, which is what stops it being one regex. The
    citation's file EXISTS here on purpose: an earlier version of this test only
    passed because it did not, so it pinned the existence filter and not the rule it
    was named for.
    """

    def setUp(self):
        # Resolved, because /tmp is a symlink on macOS and `report_files` normalises
        # the cwd it is handed.
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / ".switchboard" / "briefs" / "scout").mkdir(parents=True)
        (self.tmp / ".switchboard" / "briefs" / "scout" / "findings.md").write_text("x")
        (self.tmp / "notes").mkdir()
        (self.tmp / "notes" / "x.md").write_text("x")
        (self.tmp / "board.py").write_text("x")

    def files(self, *texts, **kw):
        return [str(Path(f).relative_to(self.tmp))
                for f in board.report_files(texts, str(self.tmp), **kw)]

    def test_a_written_file_is_opened(self):
        self.assertEqual(
            self.files("Task complete. I wrote full findings to "
                       "`.switchboard/briefs/scout/findings.md`, then called `sb done`."),
            [".switchboard/briefs/scout/findings.md"])

    def test_a_line_range_rejects_a_citation_even_when_the_file_is_right_there(self):
        self.assertEqual(
            self.files("the board's left-click handler (`board.py:1914-1929`) does it"),
            [])
        # The same file, named without a line range, is indistinguishable from one it
        # wrote — and is opened. The accepted residual, pinned so a change is deliberate.
        self.assertEqual(self.files("see `board.py`"), ["board.py"])

    def test_only_files_that_exist_under_the_agents_cwd_survive(self):
        self.assertEqual(self.files("wrote `notes/x.md` and `notes/gone.md`"),
                         ["notes/x.md"])

    def test_absolute_and_tilde_paths_are_read_and_then_contained(self):
        inside = self.tmp / "notes" / "x.md"
        self.assertEqual(self.files(f"wrote `{inside}`"), ["notes/x.md"])
        # Real, and nowhere near this agent's worktree: containment drops it.
        self.assertEqual(board.report_files(["see `/etc/hosts` and `~/.zshrc`"],
                                            str(self.tmp)), [])

    def test_urls_unfenced_prose_and_repeats_are_not_paths(self):
        self.assertEqual(self.files("see `http://example.com/a.md` and notes/x.md"), [])
        self.assertEqual(self.files("`notes/x.md`", "again: `./notes/x.md`"),
                         ["notes/x.md"])

    def test_the_cap_keeps_the_newest_message_and_leaves_it_last(self):
        for i in range(3):
            (self.tmp / "notes" / f"f{i}.md").write_text("x")
        # An earlier message naming enough files to fill the cap must not evict the
        # report the final message names — that file is the whole point of the action,
        # and it goes last so it is the tab the editor leaves in front.
        self.assertEqual(
            self.files("read `notes/f0.md` `notes/f1.md` `notes/f2.md`",
                       "Done. Findings in `notes/x.md`.", limit=2),
            ["notes/f0.md", "notes/x.md"])

    def test_every_path_comes_back_absolute_even_from_a_relative_cwd(self):
        """The one thing standing between a file named `-g.py` and `cursor -r -g -g.py`
        is that what reaches the editor is absolute. Enforced here, not inherited from
        the fact that the store happens to keep cwd absolute today."""
        (self.tmp / "-g.py").write_text("x")
        here = Path.cwd()
        self.addCleanup(os.chdir, here)
        os.chdir(self.tmp)
        got = board.report_files(["see `./-g.py` and `notes/x.md`"], ".")
        self.assertTrue(all(Path(f).is_absolute() for f in got), got)
        self.assertEqual([Path(f).name for f in got], ["-g.py", "x.md"])

    def test_a_cap_of_zero_opens_nothing(self):
        self.assertEqual(self.files("`notes/x.md`", limit=0), [])


class LastAssistantTextsTest(unittest.TestCase):
    """Only what the agent SAID — the file-opener scans this, and tool arguments and
    tool output are everything it read rather than everything it wrote."""

    def entry(self, role, *parts):
        return json.dumps({"type": role,
                           "message": {"role": role, "content": list(parts)}})

    def text(self, s):
        return {"type": "text", "text": s}

    def texts(self, *lines, n=3):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = tmp / "t.jsonl"
        p.write_text("".join(l + "\n" for l in lines))
        return board.last_assistant_texts(p, n)

    def test_text_parts_only_newest_last(self):
        got = self.texts(
            self.entry("assistant", self.text("first")),
            self.entry("assistant", {"type": "tool_use", "name": "Bash",
                                     "input": {"command": "cat notes/x.md"}}),
            self.entry("user", {"type": "tool_result", "content": "read notes/y.md"}),
            self.entry("assistant", {"type": "thinking", "thinking": "hmm"}),
            self.entry("assistant", self.text("second")),
        )
        self.assertEqual(got, ["first", "second"])

    def test_stops_at_n_skips_meta_records_and_survives_a_torn_line(self):
        got = self.texts(
            '{"type": "last-prompt", "prompt": "x"}',
            *[self.entry("assistant", self.text(f"m{i}")) for i in range(5)],
            '{"type": "ai-tit',
            n=2)
        self.assertEqual(got, ["m3", "m4"])

    def test_a_missing_transcript_is_not_an_error(self):
        self.assertEqual(board.last_assistant_texts(Path("/nope/nothing.jsonl")), [])


class OpenReportFilesTest(unittest.TestCase):
    """The failure paths, which are the ones that matter: this runs inside the event
    loop, and anything that escapes it takes the board down — permanently, if the cause
    is a settings file, because the same key kills it again on the next start."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "notes.md").write_text("x")
        self.transcript = self.tmp / "t.jsonl"

    def detail(self, transcript=None):
        return {"cwd": str(self.tmp),
                "transcript": str(transcript) if transcript else None}

    def test_an_editor_that_is_there_and_cannot_be_run_does_not_raise(self):
        # A wrapper script nobody chmodded — the shape that would otherwise kill the
        # board on every restart until the setting is fixed.
        cmd = self.tmp / "cursor"
        cmd.write_text("#!/bin/sh\n")
        cmd.chmod(0o644)
        with mock.patch.object(board, "_inspect", lambda n: self.detail()), \
             mock.patch.object(board, "_EDITOR", str(cmd)):
            self.assertEqual(board.open_report_files("w1"),
                             f"w1: {cmd} is not executable")

    def test_an_editor_that_is_not_there_says_so(self):
        with mock.patch.object(board, "_inspect", lambda n: self.detail()), \
             mock.patch.object(board, "_EDITOR", "no-such-editor-xyz"):
            self.assertEqual(board.open_report_files("w1"),
                             "w1: no-such-editor-xyz not on PATH")

    def test_a_transcript_record_whose_message_is_not_a_dict_does_not_raise(self):
        # Not a shape Claude Code writes; the file is not one switchboard writes either.
        self.transcript.write_text(
            '{"type": "assistant", "message": "hello"}\n'
            '{"type": "assistant", "message": [{"type": "text", "text": "hi"}]}\n')
        self.assertEqual(board.last_assistant_texts(self.transcript), [])
        with mock.patch.object(board, "_inspect",
                               lambda n: self.detail(self.transcript)), \
             mock.patch.object(board, "_EDITOR", "no-such-editor-xyz"):
            self.assertEqual(board.open_report_files("w1"),
                             "w1: no-such-editor-xyz not on PATH")

    def test_no_highlighted_agent_is_a_line_not_an_open(self):
        self.assertEqual(board.open_report_files(None),
                         "press o on a highlighted agent")


class OpenTickTest(unittest.TestCase):
    """The open runs off the drawing thread, because a synchronous one could freeze the
    board for the length of eight subprocess timeouts — and in raw mode ctrl-C is a byte
    in a buffer, not a signal, so nothing the human types would end it."""

    def test_the_keypress_returns_at_once_and_the_line_arrives_in_the_note(self):
        started, release = threading.Event(), threading.Event()

        def slow(name):
            started.set()
            release.wait(5)
            return f"→ {name}: opened 1 file(s)"

        note = []
        with mock.patch.object(board, "open_report_files", slow):
            run, msg = board.open_tick("w1", note, None)
            self.assertEqual(msg, "opening w1…")
            self.assertTrue(started.wait(5))
            self.assertEqual(note, [])                 # still working
            # A second double-press while the first is still going does not stack.
            again, busy = board.open_tick("w1", note, run)
            self.assertIs(again, run)
            self.assertEqual(busy,
                             "still opening w1 — w1 not started, press oo again")
            release.set()
            run[0].join(5)
        self.assertEqual(note, ["→ w1: opened 1 file(s)"])

    def test_a_thread_that_dies_still_says_something(self):
        note = []
        with mock.patch.object(board, "open_report_files",
                               mock.Mock(side_effect=RuntimeError("boom"))):
            run, _ = board.open_tick("w1", note, None)
            run[0].join(5)
        self.assertEqual(note, ["w1: open failed: boom"])

    def test_no_highlighted_agent_starts_no_thread(self):
        note = []
        run, msg = board.open_tick(None, note, None)
        self.assertIsNone(run)
        self.assertEqual(msg, "press o on a highlighted agent")


class BusyOpenNamesBothAgentsTest(unittest.TestCase):
    """`oo` on A, then on B while A is still going. B is DROPPED, not queued — so the
    line has to say so, or A's success line arriving a moment later reads as B's."""

    def test_the_refusal_names_the_one_running_and_the_one_not_started(self):
        release = threading.Event()
        note = []
        def slow(name):
            release.wait(5)
            return f"→ {name}: opened"

        with mock.patch.object(board, "open_report_files", slow):
            run, first = board.open_tick("A", note, None)
            still, second = board.open_tick("B", note, run)
            self.assertEqual(first, "opening A…")
            self.assertEqual(second, "still opening A — B not started, press oo again")
            self.assertIs(still, run)
            release.set()
            run[0].join(5)
        # And what arrives afterwards names A, so it cannot be read as B's result.
        self.assertEqual(note, ["→ A: opened"])


class DrainTest(unittest.TestCase):
    """One status line, two worker mailboxes, and an order that keeps it honest."""

    def test_the_open_wins_a_pass_it_shares_with_the_sweep(self):
        # A sweep line landing in the same pass must not swallow the answer to a key
        # somebody just pressed.
        msg, drained = board.drain("", ["sweep: nothing to do"], ["→ w1: opened 2"])
        self.assertEqual(msg, "→ w1: opened 2")
        self.assertTrue(drained)

    def test_lines_come_out_oldest_first(self):
        box = ["first", "second"]
        msg, _ = board.drain("", box)
        self.assertEqual(msg, "first")
        self.assertEqual(box, ["second"])

    def test_nothing_waiting_leaves_the_line_and_the_frame_alone(self):
        self.assertEqual(board.drain("opening w1…", [], []), ("opening w1…", False))


class HintTest(unittest.TestCase):
    """The `oo` hint: two lines, yellow, and only when there is something to open."""

    def rows(self, here, openable, renderer=board.layout, **kw):
        got = renderer(snap(agent("w1"), agent("w2")), top=0, height=20, width=90,
                       msg="", here=here, openable=openable, **kw)
        return [text for text, _ in (got or [])]

    def test_two_lines_naming_the_agent_and_the_count(self):
        lines = board.hint_lines("w1", ["/a/x.md", "/a/y.md"])
        self.assertEqual(lines, ["w1 wrote 2 files you can open",
                                 f"press oo for them in {board._EDITOR}"])

    def test_one_file_reads_as_one_file(self):
        self.assertEqual(board.hint_lines("w1", ["/a/x.md"])[0],
                         "w1 wrote 1 file you can open")

    def test_nothing_to_open_and_nobody_highlighted_are_both_no_hint(self):
        self.assertEqual(board.hint_lines("w1", []), [])
        self.assertEqual(board.hint_lines(None, ["/a/x.md"]), [])

    def test_the_plain_renderer_draws_it_in_yellow_and_keeps_its_height(self):
        with_hint = self.rows("w1", ["/a/x.md", "/a/y.md"])
        without = self.rows("w1", [])
        self.assertEqual(len(with_hint), len(without))        # slack, not extra lines
        hit = [line for line in with_hint if "wrote 2 files" in line]
        self.assertEqual(len(hit), 1)
        self.assertIn(board.HINT, hit[0])                     # yellow, and bold
        self.assertTrue(any("press oo" in line for line in with_hint))
        self.assertFalse(any("press oo" in line for line in without))

    @unittest.skipUnless(HAVE_RICH, "rich is not installed")
    def test_the_rich_renderer_draws_it_too_and_keeps_its_height(self):
        with_hint = self.rows("w1", ["/a/x.md", "/a/y.md"], renderer=richboard.layout)
        without = self.rows("w1", [], renderer=richboard.layout)
        self.assertEqual(len(with_hint), len(without))
        self.assertTrue(any("wrote 2 files" in line for line in with_hint))
        self.assertTrue(any("press oo" in line for line in with_hint))
        self.assertFalse(any("press oo" in line for line in without))

    def test_a_pane_too_short_keeps_the_tree_and_drops_the_hint(self):
        rows = board.layout(snap(*[agent(f"w{i}") for i in range(8)]), top=0, height=8,
                            width=90, msg="", here="w1", openable=["/a/x.md"])
        self.assertEqual(len(rows), 8)
        self.assertFalse(any("press oo" in text for text, _ in rows))


class ReportsCacheTest(unittest.TestCase):
    """The hint is asked on every frame, so what it costs per frame is the design.

    One `stat`, and nothing else, while the highlight sits on one agent whose transcript
    is not growing. The `sb inspect` fork and the transcript read happen off the drawing
    thread and only when the answer could have changed.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "x.md").write_text("x")
        self.transcript = self.tmp / "t.jsonl"
        self.transcript.write_text(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant",
                        "content": [{"type": "text", "text": "wrote `x.md`"}]}}) + "\n")
        self.forks = []

    def locate(self, name):
        self.forks.append(name)
        return str(self.tmp), str(self.transcript)

    def settle(self, reports):
        """Wait for the worker this frame started, the way the next frame would not."""
        for _ in range(500):
            if not reports._busy:
                return
            time.sleep(0.01)
        self.fail("the recompute never finished")

    def test_repeated_frames_with_a_stable_transcript_fork_once(self):
        reports = board.Reports()
        with mock.patch.object(board, "locate", self.locate):
            reports.tick("w1")
            self.settle(reports)
            for _ in range(50):                    # fifty frames of the same board
                files = reports.tick("w1")
            self.settle(reports)
        self.assertEqual([Path(f).name for f in files], ["x.md"])
        self.assertEqual(self.forks, ["w1"])       # ONE subprocess, not fifty-one

    def test_a_growing_transcript_recomputes_without_forking_again(self):
        reports = board.Reports()
        with mock.patch.object(board, "locate", self.locate):
            reports.tick("w1")
            self.settle(reports)
            (self.tmp / "y.md").write_text("y")
            with self.transcript.open("a") as fh:
                fh.write(json.dumps({
                    "type": "assistant",
                    "message": {"role": "assistant",
                                "content": [{"type": "text",
                                             "text": "and `y.md`"}]}}) + "\n")
            os.utime(self.transcript, (0, time.time() + 5))     # the mtime moves
            reports.tick("w1")
            self.settle(reports)
            files = reports.tick("w1")
        self.assertEqual(sorted(Path(f).name for f in files), ["x.md", "y.md"])
        self.assertEqual(self.forks, ["w1"])       # the transcript read is not a fork

    def test_an_agent_that_cannot_be_located_is_no_hint_and_no_crash(self):
        reports = board.Reports()
        with mock.patch.object(board, "locate", lambda name: None):
            reports.tick("w1")
            self.settle(reports)
            self.assertEqual(reports.tick("w1"), [])

    def test_nobody_highlighted_asks_nothing_at_all(self):
        reports = board.Reports()
        with mock.patch.object(board, "locate", self.locate):
            self.assertEqual(reports.tick(None), [])
        self.assertEqual(self.forks, [])


class DoublePressTest(unittest.TestCase):
    """`o` on its own does nothing, and the third press starts a new pair."""

    def test_one_press_does_not_fire(self):
        self.assertEqual(board.double_press(0.0, 1000.0), (False, 1000.0))

    def test_two_presses_inside_the_window_fire_once(self):
        fire, last = board.double_press(0.0, 1000.0)
        self.assertFalse(fire)
        fire, last = board.double_press(last, 1000.4)
        self.assertTrue(fire)
        # Reset-after-fire: a third press is the first half of the next double press.
        self.assertEqual(board.double_press(last, 1000.5), (False, 1000.5))

    def test_two_presses_too_far_apart_do_not_fire(self):
        _, last = board.double_press(0.0, 1000.0)
        self.assertEqual(board.double_press(last, 1002.0), (False, 1002.0))


class CoalescedPressTest(unittest.TestCase):
    """The pair that arrives in ONE terminal read — the case that used to never fire.

    A read carries whatever bytes were waiting, so two quick presses reach the loop as
    one event with `raw="oo"` whenever it was busy for a few tens of milliseconds, and
    key auto-repeat is that always. Counting, not membership, is what makes it a pair.
    """

    def test_the_boards_own_parser_hands_back_one_event_for_two_presses(self):
        events, rest = board.parse_sgr("oo")
        self.assertEqual(rest, "")
        self.assertEqual([e["raw"] for e in events], ["oo"])
        self.assertEqual(board.double_press_run(0.0, events[0]["raw"].count("o"),
                                                1000.0), (True, 0.0))

    def test_a_raw_mode_pty_really_does_coalesce_them(self):
        """Not a mock: the same pty, raw mode and blocking read the board uses."""
        primary, secondary = pty.openpty()
        self.addCleanup(os.close, primary)
        self.addCleanup(os.close, secondary)
        tty.setraw(secondary)
        os.write(primary, b"o")
        os.write(primary, b"o")
        time.sleep(0.05)                       # the loop, busy on a refresh tick
        raw = os.read(secondary, 1024).decode()
        self.assertEqual(raw, "oo")            # one read, both presses
        events, _ = board.parse_sgr(raw)
        fire, _ = board.double_press_run(0.0, events[0]["raw"].count("o"), 1000.0)
        self.assertTrue(fire)

    def test_a_lone_press_in_its_own_event_still_does_not_fire(self):
        self.assertEqual(board.double_press_run(0.0, 1, 1000.0), (False, 1000.0))

    def test_a_longer_burst_fires_once_not_once_per_pair(self):
        # Somebody leaning on the key wants the files open, not opened twice.
        self.assertEqual(board.double_press_run(0.0, 5, 1000.0), (True, 1000.0))


if __name__ == "__main__":
    unittest.main()
