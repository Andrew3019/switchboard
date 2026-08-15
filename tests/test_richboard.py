"""The rich renderer — the four things that break silently.

`tests/test_board.py` pins the plain renderer and still does: `board.layout` is untouched
and every one of those tests calls it directly. What is pinned HERE is the seam and the
three decisions the wiring had to make, and nothing about appearance. A misdrawn panel
still looks like a panel; a panel one line taller than it measured focuses the wrong agent
on the next click, and looks exactly like a correct one.

Four, not more, and each is a decision rather than a reassurance:

1. no line wraps, measured by `board`'s own column arithmetic, on the characters that
   break it — CJK, ZWJ emoji, variation selectors, flag pairs;
2. a click on screen row N resolves to the agent DRAWN on screen row N, including in the
   NEEDS YOU block and across a scroll;
3. a missing `rich` falls back rather than crashing;
4. the two gutter cases the mockup could not decide — a group cut by the scroll, and a
   workspace shared at depth 0.

Skipped whole when `rich` is absent, except (3), which is the test for exactly that.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from switchboard import board, richboard, status  # noqa: E402

HAVE_RICH = richboard.available()


def agent(name, *, depth=0, parent=None, state="working", herdr_state="working",
          alive=True, stalled=False, gone=False, unread=0, task=None, blocked_why=None,
          workspace="api", idle=5, undelivered=0, turn="working"):
    return status.AgentStatus(
        name=name, role="worker", parent=parent, depth=depth, state=state,
        herdr_state=herdr_state, alive=alive, stalled=stalled, gone=gone, unread=unread,
        age=100, idle=idle, last_activity=0, workspace=workspace, task=task,
        blocked_why=blocked_why, summary=None, turn=turn, undelivered=undelivered,
        undelivered_age=60 if undelivered else 0)


def snap(*agents):
    return status.Snapshot(now=0, agents=list(agents))


def frame(s, *, top=0, height=20, width=80, msg="", note_text=""):
    rows = richboard.layout(s, top=top, height=height, width=width, msg=msg,
                            note_text=note_text, show_archived=False)
    assert rows is not None, "the rich renderer declined this frame"
    return rows


@unittest.skipUnless(HAVE_RICH, "rich is not installed here")
class NoLineWrapsTest(unittest.TestCase):
    """THE ONE INVARIANT THE VIEW RESTS ON, on the characters that break it.

    A wrapped line pushes every row below it down by one and the next click focuses the
    wrong agent — silently. `rich` measures in cells and `board._visible_len` counts
    columns its own way, and the whole wiring assumes the two agree; this is where that
    assumption is checked rather than believed.
    """

    WIDE = snap(
        agent("日本語エージェント", workspace="w1"),
        agent("👩‍👩‍👧‍👦-family", depth=1, parent="日本語エージェント", workspace="w2",
              blocked_why="研究の途中で止まりました — 次はどうしますか", state="blocked",
              turn="idle"),
        agent("flag-🇯🇵🇺🇸", depth=1, parent="日本語エージェント", workspace="w2",
              unread=3, undelivered=1),
        agent("plane-✈️-vs16", depth=1, parent="日本語エージェント", workspace="w3",
              stalled=True, turn="idle", idle=900),
        agent("text-✈︎-vs15", depth=1, parent="日本語エージェント", workspace="w3",
              gone=True, alive=False),
    )

    def test_no_line_is_ever_wider_than_the_pane(self):
        for width in (24, 40, 56, 80, 120):
            for height in (6, 12, 24):
                with self.subTest(width=width, height=height):
                    for text, _ in frame(self.WIDE, width=width, height=height):
                        self.assertLessEqual(board._visible_len(text), width, repr(text))

    def test_every_line_fills_the_pane_exactly_so_the_panel_cannot_be_ragged(self):
        """Stronger than "does not overflow", and the half that catches a SHORT line.

        The panel's right border is the last column of every line, so an exact width is
        the same statement as "the frame is rectangular". A row `rich` measured as one
        column narrower than `board` did would still pass the test above and would show
        up here.
        """
        for text, _ in frame(self.WIDE, width=72, height=20):
            self.assertEqual(board._visible_len(text), 72, repr(text))

    def test_rich_and_board_agree_so_the_last_resort_clip_never_fires(self):
        """`board._fit` strips a line's colour to save its correctness, and it is applied
        on the way out of `_lines` for exactly the case where the two measurements
        disagree. If it ever fires, the line comes back plain — so a coloured frame is the
        proof that it did not have to."""
        rows = frame(self.WIDE, width=80, height=20)
        self.assertTrue(all("\033[" in text for text, _ in rows),
                        "a line lost its colour, so board._fit had to rescue it")


@unittest.skipUnless(HAVE_RICH, "rich is not installed here")
class ClickMappingTest(unittest.TestCase):
    """A row means the agent DRAWN on it, and `agent_at` is still nothing but an index."""

    FLEET = snap(
        agent("top", workspace="top"),
        agent("alpha", depth=1, parent="top", workspace="ws-a"),
        agent("beta", depth=1, parent="top", workspace="ws-a", state="blocked",
              turn="idle", blocked_why="which branch?"),
        agent("gamma", depth=1, parent="top", workspace="ws-b", stalled=True,
              turn="idle", idle=800),
        agent("delta", depth=1, parent="top", workspace="ws-c"),
        agent("epsilon", depth=1, parent="top", workspace="ws-c"),
    )

    def _check(self, rows):
        seen = 0
        for i, (text, owner) in enumerate(rows, 1):
            self.assertIs(board.agent_at(rows, i), owner)
            if owner is None:
                continue
            seen += 1
            plain = text.replace("\033", "")
            self.assertIn(owner.name, plain,
                          f"row {i} is owned by {owner.name} but does not name it")
        self.assertGreater(seen, 0)

    def test_a_click_resolves_to_the_agent_written_on_that_row(self):
        self._check(frame(self.FLEET, width=80, height=20))

    def test_it_still_holds_when_the_list_is_scrolled(self):
        for top in (1, 2, 3, 99):
            with self.subTest(top=top):
                self._check(frame(self.FLEET, width=80, height=10, top=top))

    def test_the_needs_you_rows_focus_the_agent_they_name(self):
        rows = frame(self.FLEET, width=80, height=20)
        owners = [o.name for _, o in rows if o is not None]
        # `beta` and `gamma` are drawn twice — once as their own row, once in NEEDS YOU —
        # and both lines have to point at them. A summons a click cannot follow is worse
        # than no summons.
        self.assertEqual(owners.count("beta"), 2)
        self.assertEqual(owners.count("gamma"), 2)

    def test_chrome_and_padding_are_owned_by_nobody(self):
        rows = frame(self.FLEET, width=80, height=24)
        self.assertIsNone(rows[0][1])                       # the top border
        self.assertIsNone(rows[1][1])                       # the header bar
        self.assertIsNone(rows[-1][1])                      # the bottom border
        self.assertIsNone(rows[-2][1])                      # the footer
        blanks = [o for text, o in rows
                  if not board._ANSI.sub("", text).strip("│ ")]
        self.assertTrue(blanks and all(o is None for o in blanks))


@unittest.skipUnless(HAVE_RICH, "rich is not installed here")
class FooterTest(unittest.TestCase):
    """The footer offers only what the board actually does.

    It used to draw `x  clear N gone`, which no key ever read. An offer nothing answers is
    worse than no offer, so it is gone and stays gone until something implements it.
    """

    FLEET = snap(agent("top", workspace="top"),
                 agent("ghost", depth=1, parent="top", workspace="ws",
                       gone=True, alive=False))

    def _footer_line(self, width=80, **kw):
        rows = frame(self.FLEET, width=width, height=20, **kw)
        return board._ANSI.sub("", rows[-2][0])

    def test_a_gone_agent_does_not_buy_a_clear_offer(self):
        self.assertNotIn("clear", self._footer_line())

    def test_the_hint_line_still_reads(self):
        self.assertIn("q quits", self._footer_line())

    def test_a_stale_note_still_outranks_the_hints(self):
        line = self._footer_line(note_text="snapshot is 40s old")
        self.assertTrue(line.strip("│ ").startswith("snapshot is 40s old"), repr(line))

    def test_the_note_and_the_hints_do_not_run_together(self):
        # They used to: the separator was built into the piece, and `board._clip` flattens
        # whitespace, so it never reached the screen — "40s oldclick a row to focus it".
        line = self._footer_line(note_text="snapshot is 40s old")
        self.assertIn("snapshot is 40s old · click a row to focus it", line)

    def test_a_narrow_footer_still_fits_its_pane_exactly(self):
        # The no-wrap invariant: the separator is width like anything else, and a pane too
        # narrow for the hints drops them rather than spilling over.
        for width in (46, 40, 34, 30):
            line = self._footer_line(width=width, note_text="snapshot is 40s old")
            self.assertEqual(board._visible_len(line), width, repr(line))


class FallbackTest(unittest.TestCase):
    """A MISSING DEPENDENCY IS A CHANGE OF APPEARANCE AND NOTHING ELSE.

    `rich` is switchboard's first ever runtime dependency and there is no packaging file
    to make it present, so this is not a hypothetical: `bin/sb` runs under whatever
    `python3` is on PATH, and one interpreter on a machine has it where the next does not.
    """

    FLEET = snap(agent("top", workspace="top"),
                 agent("kid", depth=1, parent="top", workspace="ws"))

    def test_without_rich_the_board_still_draws_and_still_maps_clicks(self):
        # `sys.modules[name] = None` is what the import system itself uses to record a
        # failed import: `import rich.box` under it raises ImportError. Nothing is faked
        # and no test double learns a new trick — the module is simply not importable,
        # which is the production condition exactly.
        blocked = {name: None for name in
                   ("rich", "rich.box", "rich.console", "rich.panel", "rich.text")}
        with mock.patch.dict(sys.modules, blocked), \
                mock.patch.object(richboard, "_HAVE", None):
            self.assertFalse(richboard.available())
            self.assertIsNone(richboard.layout(self.FLEET, top=0, height=20, width=80,
                                               msg="", note_text=""))
            rows = board._frame(self.FLEET, top=0, height=20, width=80, msg="",
                                note_text="", show_archived=False)
        self.assertEqual(len(rows), 20)
        self.assertEqual([o.name for _, o in rows if o is not None], ["top", "kid"])
        for i, (_, owner) in enumerate(rows, 1):
            self.assertIs(board.agent_at(rows, i), owner)

    def test_a_pane_too_small_to_be_a_panel_falls_back_rather_than_lying(self):
        self.assertIsNone(richboard.layout(self.FLEET, top=0, height=3, width=80,
                                           msg="", note_text=""))
        rows = board._frame(self.FLEET, top=0, height=3, width=80, msg="",
                            note_text="", show_archived=False)
        self.assertEqual(len(rows), 3)


@unittest.skipUnless(HAVE_RICH, "rich is not installed here")
class GutterTest(unittest.TestCase):
    """The two cases the mockup never had to answer, pinned as answers.

    A run of rows sharing a workspace is bracketed `╭ │ ╰`; a workspace of one gets `·`;
    a top alone in its own workspace gets nothing.
    """

    def _marks(self, rows):
        """The gutter character on each line, in order, or `None`."""
        out = []
        for text, owner in rows:
            if owner is None or board._is_group(owner):
                continue
            # The LEFT of the line only. The panel's own border is a `│` in
            # column 0 and a tail can hold a `·` separator; the gutter is always
            # inside the row's indentation, which is these few columns.
            plain = board._ANSI.sub("", text)[2:14]
            out.append(next((c for c in plain if c in "╭│╰·"), None))
        return out

    def test_a_group_cut_by_the_scroll_shows_no_corner_at_the_cut(self):
        """A CORNER MEANS "THE GROUP ENDS HERE". At the edge of a scrolled window it
        would be a lie: the group carries on, off-screen, and a `│` says so."""
        fleet = snap(agent("top", workspace="top"),
                     *[agent(f"k{i}", depth=1, parent="top", workspace="shared")
                       for i in range(4)])
        whole = self._marks(frame(fleet, width=80, height=20))
        self.assertEqual(whole, [None, "╭", "│", "│", "╰"])
        # Scrolled one row down: the group's first row is off the top, so nothing on
        # screen may claim to be its start.
        cut = self._marks(frame(fleet, width=80, height=8, top=2))
        self.assertTrue(cut and cut[0] == "│", cut)
        self.assertNotIn("╭", cut)

    def test_a_workspace_shared_at_depth_zero_is_marked_and_a_top_alone_is_not(self):
        """qa-2 found this on Andrew's own board: the mockup skipped every run whose
        shallowest row is depth 0, so two agents sharing one checkout under the human got
        no mark at all. They get a bracket, drawn in the leading space each row already
        spends before its glyph — zero columns, and no indenting of the board, which
        Andrew ruled out."""
        fleet = snap(agent("solo", workspace="solo"),
                     agent("main", workspace="main"),
                     agent("debug", depth=1, parent="main", workspace="main"))
        self.assertEqual(self._marks(frame(fleet, width=80, height=20)),
                         [None, "╭", "╰"])
