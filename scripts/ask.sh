#!/usr/bin/env bash
# Demo beat 3: talk to the agent over the HTTP API.
#
#   scripts/ask.sh "terminate instance i-0123456789abcdef0"
#   scripts/ask.sh "scale leash-dev-asg to 10"
#
# POSTs {"message": "..."} to /ask and prints the agent's reply. The denial
# (and the Cedar policy id that caused it) shows up in the reply and on the
# dashboard's audit table.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_cmd aws curl python

message="${1:-}"
[[ -n "$message" ]] || die "usage: scripts/ask.sh \"<message for the agent>\""

api_url="$(stack_output ApiUrl)"
log "POST $api_url/ask"

# JSON-encode the message with python so quotes and newlines are safe.
body="$(python -c 'import json, sys; print(json.dumps({"message": sys.argv[1]}))' "$message")"

# --max-time 120: the agent may run SSM commands and wait for them.
response="$(curl -sS --max-time 120 -X POST "$api_url/ask" \
  -H 'content-type: application/json' -d "$body")"

# Pretty-print the reply if it is JSON, otherwise show the raw body.
printf '%s' "$response" | python -c '
import json, sys
raw = sys.stdin.read()
try:
    data = json.loads(raw)
except ValueError:
    print(raw); sys.exit(0)
if isinstance(data, dict) and "reply" in data:
    print("incident:", data.get("incident_id", "-"))
    print()
    print(data["reply"])
else:
    print(json.dumps(data, indent=2))
'
