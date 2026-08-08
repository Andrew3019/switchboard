#!/usr/bin/env bash
# THROWAWAY. Minimal `wf` to validate the M3 verb design with real agents.
# Store = files in $WF_HOME. No SQLite, no M1. Delete once M1 exists.
set -uo pipefail
H="${HERDR:-$HOME/.local/bin/herdr}"
# Where switchboard itself lives, so this script can call into it the same way bin/sb does.
SB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WF_HOME="${WF_HOME:-/tmp/wf-poc}"
# Identity comes from the agent's OWN session id (native), NOT an injected env var.
# Injected env breaks whenever pane creation changes (tab create carries no --env).
ME="${WF_ME:-}"
if [ -z "$ME" ] && [ -n "${CLAUDE_CODE_SESSION_ID:-}" ]; then
  ME=$(grep -l " ${CLAUDE_CODE_SESSION_ID} " "$WF_HOME"/agents/* 2>/dev/null | head -1 | xargs -r basename)
fi
ME="${ME:-human}"
mkdir -p "$WF_HOME"/{agents,msgs}

now(){ date +%s; }
newid(){ echo "$(date +%s)$RANDOM"; }
poke(){ $H agent prompt "$1" "$2" >/dev/null 2>&1; }

case "${1:-}" in

delegate)  # wf delegate "<task>" --role R [--name N] [--model <tier>] [--parent P]
  shift; TASK="$1"; shift
  ROLE=worker; NAME=""; MODEL=""; PARENT="$ME"
  while [ $# -gt 0 ]; do case "$1" in
    --role) ROLE="$2"; shift 2;; --name) NAME="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;; --parent) PARENT="$2"; shift 2;; *) shift;; esac; done
  [ -z "$NAME" ] && NAME="$ROLE-$(ls "$WF_HOME/agents" 2>/dev/null | wc -l | tr -d ' ')"
  # One agent per TAB: pane splits exhaust after ~4 (no room), which silently breaks fan-out.
  P=$($H tab create --no-focus 2>/dev/null \
      | python3 -c "import json,sys;d=json.load(sys.stdin)['result'];print(d.get('tab',{}).get('pane_id') or d.get('pane',{}).get('pane_id',''))" 2>/dev/null)
  [ -z "$P" ] && P=$($H pane split --no-focus --direction down --ratio 0.3 2>/dev/null \
      | python3 -c "import json,sys;print(json.load(sys.stdin)['result']['pane']['pane_id'])" 2>/dev/null)
  [ -z "$P" ] && { echo '{"error":"no pane available"}'; exit 1; }
  sleep 4   # finding #12: pane needs to reach a shell prompt
  # A tier name in, provider flags out. This shell knows no model names and no tier names:
  # it used to pin `cheap` to a model id here, which went stale the day that id was retired
  # and could not express effort at all. switchboard/models.py is the one place allowed to
  # know either. Unquoted on use, deliberately — it is several words. If resolution fails
  # (no python3, broken config) we spawn with no --model, which is what omitting the flag
  # has always meant: the provider CLI picks its own default.
  MODELARG=$(PYTHONPATH="$SB_ROOT" python3 -c \
    'import sys; from switchboard import models; print(" ".join(models.resolve(sys.argv[1] or None, sys.argv[2]).cli_args()))' \
    "$MODEL" "$PWD" 2>/dev/null)
  # herdr rejects multi-line agent args (invalid_agent_argument). Role line MUST be single-line.
  # The verb docs live in CLAUDE.md instead (written by `wf init`), so they cost nothing per agent.
  SID=$($H agent start "$NAME" --kind claude --pane "$P" --timeout 90000 -- \
        --permission-mode auto $MODELARG \
        --append-system-prompt "You are agent '$NAME', role '$ROLE'. Your parent is '$PARENT'. Follow the wf protocol in CLAUDE.md. ALWAYS finish by calling: wf done \"<one-line summary>\"" \
        2>/dev/null | python3 -c "import json,sys;print(json.load(sys.stdin)['result']['agent']['agent_session']['value'])" 2>/dev/null)
  printf '%s\n' "$NAME $PARENT $P $SID $ROLE " > "$WF_HOME/agents/$NAME"
  poke "$NAME" "$TASK"
  echo "{\"name\":\"$NAME\",\"pane\":\"$P\",\"session\":\"$SID\"}"
  ;;

tell)  # wf tell <who> "<msg>"
  shift; WHO="$1"; MSG="$2"
  [ "$WHO" = "parent" ] && WHO=$(awk '{print $2}' "$WF_HOME/agents/$ME" 2>/dev/null || echo human)
  ID=$(newid); printf '%s\t%s\t%s\t%s\n' "$ID" "$ME" "$WHO" "$MSG" > "$WF_HOME/msgs/$ID.$WHO"
  [ "$WHO" != "human" ] && poke "$WHO" "You have mail. Run: wf inbox"
  echo "{\"sent\":\"$ID\",\"to\":\"$WHO\"}"
  ;;

done)  # wf done "<summary>"
  shift; SUM="${1:-}"
  PARENT=$(awk '{print $2}' "$WF_HOME/agents/$ME" 2>/dev/null || echo human)
  PANE=$(awk '{print $3}' "$WF_HOME/agents/$ME" 2>/dev/null)
  ID=$(newid); printf '%s\t%s\t%s\t[DONE] %s\n' "$ID" "$ME" "$PARENT" "$SUM" > "$WF_HOME/msgs/$ID.$PARENT"
  [ -n "$PANE" ] && $H pane report-agent "$PANE" --source wf --agent "$ME" --state idle --seq "$(now)" >/dev/null 2>&1
  [ "$PARENT" != "human" ] && poke "$PARENT" "A child finished. Run: wf inbox"
  echo "{\"done\":\"$ME\"}"
  ;;

inbox)
  F=$(ls "$WF_HOME"/msgs/*."$ME" 2>/dev/null)
  [ -z "$F" ] && { echo '{"messages":[]}'; exit 0; }
  echo "MESSAGES:"; for f in $F; do awk -F'\t' '{printf "  from=%s: %s\n",$2,$4}' "$f"; mv "$f" "$f.read"; done
  ;;

status)
  for a in "$WF_HOME"/agents/*; do [ -e "$a" ] || continue; awk '{printf "  %s (role=%s, parent=%s)\n",$1,$5,$2}' "$a"; done
  ;;

*) echo "usage: wf delegate|tell|done|inbox|status"; exit 1;;
esac
