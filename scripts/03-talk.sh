#!/usr/bin/env bash
# The PoC in miniature: doorbell + mailbox, with files standing in for SQLite.
# If this works, the real version is the same thing with a database.
#
# COSTS TOKENS — spawns two live agents.
# Usage: ./03-talk.sh <agent-a-name> <agent-b-name>
set -uo pipefail

HERDR="${HERDR:-$HOME/.local/bin/herdr}"
A="${1:?usage: 03-talk.sh <agent-a> <agent-b>   (names from: herdr agent list)}"
B="${2:?usage: 03-talk.sh <agent-a> <agent-b>}"
BOX="${BOX:-/tmp/wf-smoke}"; mkdir -p "$BOX"

MSG_ID=$(date +%s)

echo "== 1. A writes a message to the mailbox (payload NEVER crosses a terminal) =="
cat > "$BOX/$MSG_ID.msg" <<EOF
{"id":"$MSG_ID","from":"$A","to":"$B","kind":"ask",
 "body":"Reply with the single word PONG using the command shown."}
EOF
echo "  wrote $BOX/$MSG_ID.msg"

echo
echo "== 2. doorbell: poke B. The poke carries NO payload. =="
"$HERDR" agent prompt "$B" \
  "You have mail. Run: cat $BOX/$MSG_ID.msg — then write your reply to $BOX/$MSG_ID.reply and stop." \
  2>&1 | sed 's/^/  /'

echo
echo "== 3. A blocks on the store, not on the terminal =="
echo -n "  waiting for reply"
for i in $(seq 1 60); do
  [ -f "$BOX/$MSG_ID.reply" ] && { echo; echo "  GOT: $(cat "$BOX/$MSG_ID.reply")"; break; }
  echo -n "."; sleep 2
done
[ -f "$BOX/$MSG_ID.reply" ] || { echo; echo "  TIMEOUT — a real ask() needs this path (C9)."; }

echo
echo "== what to learn =="
cat <<'EOF'
  1. Did `agent prompt` land while B was mid-turn, or did it need B idle?
  2. Did B reliably follow a 2-step instruction, or does it need a real tool?
     (If unreliable -> that's the argument for `wf` as a CLI, not prose.)
  3. How long from poke to reply? That sets the ask() timeout default.
  4. Did B stop cleanly, or keep going? (-> the Stop-hook question, C6)
EOF
