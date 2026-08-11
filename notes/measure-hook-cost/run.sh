#!/bin/bash
# In-situ: the same real Claude Code task, with and without activity hooks installed.
# $1 = label (nohook|full|cheap), $2 = settings file or "none", $3 = run index
set -u
S=/private/tmp/claude-501/-Users-andrew--herdr-worktrees-switchboard-measure-hook-cost/37363a75-26af-413c-8e12-1b3b87915e3a/scratchpad
CLONE=$S/clone
WORK=$CLONE/work
LOG=$S/insitu/hooklog-$1-$3.txt
export SB_HOOK_LOG=$LOG
: > "$LOG"

PROMPT='In the directory ./work, read every file f01.txt through f12.txt using the Read tool, one Read call per file, in order. Do not use Bash, Glob, or Grep. When you have read all twelve, reply with only the word DONE.'

cd "$CLONE" || exit 1
t0=$(/opt/homebrew/bin/python3 -c 'import time;print(time.time())')
if [ "$2" = "none" ]; then
  claude -p "$PROMPT" --allowedTools Read --model sonnet > "$S/insitu/out-$1-$3.txt" 2>&1
else
  claude -p "$PROMPT" --allowedTools Read --model sonnet --settings "$2" > "$S/insitu/out-$1-$3.txt" 2>&1
fi
t1=$(/opt/homebrew/bin/python3 -c 'import time;print(time.time())')
fires=$(wc -l < "$LOG" | tr -d ' ')
echo "$1 run$3 wall=$(/opt/homebrew/bin/python3 -c "print(round($t1-$t0,2))")s hook_firings=$fires"
