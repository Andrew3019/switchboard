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

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import board, panel, status  # noqa: E402


def agent(name, *, depth=0, state="working", herdr_state="working", alive=True,
          stalled=False, gone=False, unread=0, task=None, blocked_why=None,
          summary=None, parent=None, archived=False):
    """One agent. `archived=True` sets what being absent from herdr past the spawn
    grace actually looks like, so the real `AgentStatus.archived` decides — nothing
    here mocks the predicate."""
    return status.AgentStatus(
        name=name, role="worker", parent=parent, depth=depth, state=state,
        herdr_state=None if archived else herdr_state,
        alive=False if archived else alive,
        stalled=stalled, gone=gone, unread=unread,
        age=int(status.SPAWN_GRACE) + 1 if archived else 10,
        idle=5, last_activity=0, workspace="api", task=task,
        blocked_why=blocked_why, summary=summary,
    )


def snap(*agents):
    return status.Snapshot(now=0, agents=list(agents))


class ParseSgrTest(unittest.TestCase):
    def test_a_click_decodes_to_button_column_and_row(self):
        events, rest = board.parse_sgr("\033[<0;12;7M")
        self.assertEqual(rest, "")
        self.assertEqual([e["button"] for e in events], [0])
        self.assertEqual((events[0]["col"], events[0]["row"]), (12, 7))
        self.assertTrue(board.is_left_click(events[0]))

    def test_a_release_is_not_a_click(self):
        [ev], _ = board.parse_sgr("\033[<0;12;7m")
        self.assertFalse(board.is_left_click(ev))

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
        self.assertEqual(board.note(a), "GONE — herdr has no such agent")

    def test_every_glyph_has_a_colour_and_they_are_all_distinct(self):
        kinds = [agent("a", gone=True), agent("b", state="blocked"),
                 agent("c", stalled=True), agent("d", state="done"),
                 agent("e", alive=None), agent("f")]
        glyphs = [board.glyph(a) for a in kinds]
        self.assertEqual(len(set(glyphs)), len(glyphs))
        for g in glyphs:
            self.assertIn(g, board._GLYPH_COLOR)

    def test_a_stalled_agent_wants_you_even_though_it_does_not_know_it(self):
        self.assertTrue(board.wants_you(agent("w", stalled=True)))
        self.assertTrue(board.wants_you(agent("w", gone=True)))
        self.assertFalse(board.wants_you(agent("w")))

    def test_only_one_note_is_ever_shown_and_it_is_the_most_actionable(self):
        a = agent("w", state="blocked", blocked_why="need a key", unread=2,
                  task="do the thing")
        self.assertEqual(board.note(a), "BLOCKED — need a key")


class LayoutTest(unittest.TestCase):
    def test_a_click_resolves_to_the_agent_drawn_on_that_row(self):
        rows = board.layout(snap(agent("one"), agent("two", depth=1), agent("three")),
                            top=0, height=12, width=100, msg="")
        drawn = [(i + 1, a.name) for i, (_, a) in enumerate(rows) if a is not None]
        self.assertEqual([n for _, n in drawn], ["one", "two", "three"])
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
        self.assertEqual(board.agent_at(first, 3).name, "a0")
        self.assertEqual(board.agent_at(later, 3).name, "a3")

    def test_scrolling_past_the_end_stops_rather_than_emptying_the_view(self):
        agents = [agent(f"a{i}") for i in range(6)]
        rows = board.layout(snap(*agents), top=999, height=10, width=100, msg="")
        self.assertTrue([a for _, a in rows if a is not None])

    def test_no_line_may_wrap_because_a_wrapped_line_shifts_every_click_below_it(self):
        wide = agent("w", task="x" * 400)
        rows = board.layout(snap(wide), top=0, height=10, width=40, msg="m" * 200)
        for text, _ in rows:
            self.assertLessEqual(board._visible_len(text), 40)

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
        self.assertIn(status.summary_line(s), rows[0][0])


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
            snap, note_text = board.refresh(self.sup)
        self.assertEqual(note_text, "")
        self.assertTrue(snap.agents[0].gone)          # the screen says it, exactly as before
        rows = board.layout(snap, top=0, height=10, width=120, msg="", note_text=note_text)
        self.assertEqual(board.agent_at(rows, 3).name, "w1")

    def test_an_old_snapshot_is_labelled_rather_than_drawn_as_now(self):
        """The failure a shared cache introduces, and the one thing the design asked to be
        loud: forty panes quietly agreeing on stale data."""
        self._publish(collected_at=panel.now() - 40)
        with mock.patch.object(panel, "ensure_collector", lambda *a, **k: False):
            snap, note_text = board.refresh(self.sup)
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
            snap, note_text = board.refresh(self.sup)
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
        return [a for _, a in rows if a is not None]

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
        height = board.CHROME + 3                       # capacity 3, 5 rows to show

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
        # capacity = height - CHROME; small enough that something really is below.
        height = board.CHROME + 3
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
        rows = board.layout(snap(*unknown), top=0, height=12, width=100, msg="")
        self.assertEqual([a.name for a in self.drawn(rows)], ["a0", "a1", "a2", "a3"])
        self.assertNotIn("archived", self.body(rows))

    def test_the_hint_line_says_how_to_see_them(self):
        """The collapsed row is visible where a keybinding is not."""
        rows = board.layout(snap(agent("one")), top=0, height=12, width=200, msg="")
        self.assertIn("a archived", self.text(rows))

    def test_the_header_still_counts_every_agent_a_collapse_hid(self):
        """Collapse shortens the tree, not the readout. Three agents, two rows — so a
        header that had quietly started counting rows would read "2 agents" here."""
        s = snap(agent("main"),
                 agent("d1", depth=1, parent="main", archived=True),
                 agent("d2", depth=1, parent="main", archived=True))
        rows = board.layout(s, top=0, height=12, width=200, msg="")
        self.assertEqual(len(self.drawn(rows)), 2)
        self.assertIn("3 agents", rows[0][0])
        self.assertIn(status.summary_line(s), rows[0][0])


if __name__ == "__main__":
    unittest.main()
