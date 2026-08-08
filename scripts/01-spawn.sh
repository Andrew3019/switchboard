#!/usr/bin/env bash
# Build a run's scaffolding entirely from a script. No agent decides any of this.
# Proves: worktree -> workspace -> pane -> agent start.
#
# Usage: ./01-spawn.sh <repo-path> <run-name>
set -uo pipefail

HERDR="${HERDR:-$HOME/.local/bin/herdr}"
REPO="${1:?usage: 01-spawn.sh <repo-path> <run-name>}"
RUN="${2:?usage: 01-spawn.sh <repo-path> <run-name>}"

echo "== 1. worktree =="
# herdr owns this; we never call `git worktree` ourselves.
"$HERDR" worktree create --branch "wf/$RUN" --base main 2>&1 | sed 's/^/  /'
echo "  (if this failed: check --base matches the repo's default branch)"

echo
echo "== 2. workspace =="
"$HERDR" workspace create "$RUN" 2>&1 | sed 's/^/  /'

echo
echo "== 3. pane =="
# agent start needs a PRE-EXISTING IDLE SHELL PANE. It never creates topology.
"$HERDR" pane split 2>&1 | sed 's/^/  /'
echo "  capture the pane id from above -> \$PANE"

echo
echo "== 4. start the agent =="
echo "  herdr agent start <name> --kind claude --pane \$PANE -- --permission-mode auto"
echo "  ^ ALWAYS pass --permission-mode auto. Default is manual; agents would sit waiting."
echo "  (not run automatically — costs nothing until prompted, but be deliberate)"

echo
echo "== 5. what exists now =="
"$HERDR" workspace list 2>&1 | sed 's/^/  /'
"$HERDR" agent list 2>&1 | sed 's/^/  /'

echo
echo "LEARN: which of these need ids threaded through, and what each returns."
echo "That return-shape plumbing IS the M2 adapter."
