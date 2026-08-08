#!/usr/bin/env bash
# THE LOAD-BEARING TEST. Does our reported state beat herdr's regex detector, and stick?
# If this fails, M2's design is wrong and the whole doorbell scheme leans on sand.
#
# Usage: ./02-state.sh <pane-id>
set -uo pipefail

HERDR="${HERDR:-$HOME/.local/bin/herdr}"
PANE="${1:?usage: 02-state.sh <pane-id>   (get one from: herdr pane list)}"
SRC="wf-smoke"          # our source id. Pick one, keep it forever.
SEQ=1                   # strictly monotonic PER SOURCE. Never reuse, never roll back.

state() { "$HERDR" agent list 2>/dev/null | grep -i "$PANE" || "$HERDR" pane get "$PANE" 2>&1 | head -5; }

echo "== baseline =="; state | sed 's/^/  /'

echo
echo "== claim authority: report blocked (seq=$SEQ) =="
"$HERDR" pane report-agent "$PANE" --source "$SRC" --agent "smoketest" \
    --state blocked --message "held by $SRC" --seq $SEQ 2>&1 | sed 's/^/  /'
sleep 1; state | sed 's/^/  /'
echo "  EXPECT: blocked"

echo
echo "== does it stick? (wait, re-read) =="
sleep 3; state | sed 's/^/  /'
echo "  EXPECT: still blocked. Authority has no TTL."

echo
echo "== stale seq must be SILENTLY DROPPED (returns ok anyway!) =="
"$HERDR" pane report-agent "$PANE" --source "$SRC" --agent "smoketest" --state idle --seq $SEQ 2>&1 | sed 's/^/  /'
sleep 1; state | sed 's/^/  /'
echo "  EXPECT: STILL BLOCKED, and the command above still said ok."
echo "  ^^ this is the trap: a dropped write reports success. Adapter must own seq."

echo
echo "== advance seq -> should take effect =="
SEQ=$((SEQ+1))
"$HERDR" pane report-agent "$PANE" --source "$SRC" --agent "smoketest" --state working --seq $SEQ 2>&1 | sed 's/^/  /'
sleep 1; state | sed 's/^/  /'
echo "  EXPECT: working"

echo
echo "== MANUAL: type in the pane so the detector sees a spinner/prompt =="
echo "  Then re-run: herdr pane get $PANE"
echo "  EXPECT: our state still wins. ONLY a live permission-prompt can force 'blocked'."

echo
echo "== release authority back to the detector =="
SEQ=$((SEQ+1))
"$HERDR" pane release-agent "$PANE" --source "$SRC" --agent "smoketest" --seq $SEQ 2>&1 | sed 's/^/  /'
echo "  ALSO TRY: herdr pane clear-agent-authority $PANE"
echo "  LEARN: how these two differ. Docs don't say; we need to know for cleanup."
