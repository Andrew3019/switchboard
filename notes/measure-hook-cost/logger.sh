#!/bin/bash
p=$(cat)
echo "$(date +%s.%N) $(echo "$p" | /usr/bin/python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("hook_event_name"),d.get("tool_name"))' 2>/dev/null)" >> "$SB_EVENT_LOG"
exit 0
