#!/usr/bin/env bash
# Read-only. Costs nothing. Confirms the ground we're building on.
set -uo pipefail

HERDR="${HERDR:-$HOME/.local/bin/herdr}"
MIN_VERSION="0.8.0"

echo "== herdr binary =="
command -v "$HERDR" >/dev/null || { echo "MISSING: $HERDR"; exit 1; }
VER=$("$HERDR" --version | awk '{print $2}')
echo "  version: $VER  (pinned minimum: $MIN_VERSION)"
[ "$VER" = "$MIN_VERSION" ] || echo "  !! version drift — re-check reference/ docs"

echo
echo "== server =="
"$HERDR" status 2>&1 | sed 's/^/  /'

echo
echo "== protocol (must match our schema copy) =="
python3 -c "import json;print('  protocol', json.load(open('$(dirname "$0")/../reference/herdr-api-schema.json'))['protocol'])" 2>/dev/null \
  || echo "  (schema copy not readable)"

echo
echo "== integrations =="
"$HERDR" integration status 2>&1 | sed 's/^/  /'
echo "  NOTE: we need 'claude' installed. If absent: herdr integration install claude"

echo
echo "== live session =="
"$HERDR" agent list 2>&1 | head -20 | sed 's/^/  /'

echo
echo "== socket =="
ls -l "$HOME/.config/herdr/herdr.sock" 2>&1 | sed 's/^/  /'
echo
echo "preflight done."
