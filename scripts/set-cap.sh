#!/usr/bin/env bash
# Live policy edit: change the scale cap in the policy bucket and watch the next decision change.
#
#   scripts/set-cap.sh 2        # ForbidScaleAboveCap now refuses desiredCapacity > 2
#   scripts/set-cap.sh 4        # back to the default
#
# No redeploy, no restart: the authorizer Lambda re-reads cedar/ from S3 whenever an object's
# ETag changes, so the edit is in force on the very next authorisation. The bucket is
# versioned, so every previous policy text is one `aws s3api list-object-versions` away.
# The new text is validated against the schema with cedarpy before it is uploaded.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_cmd aws python

cap="${1:-}"
[[ "$cap" =~ ^[0-9]+$ ]] || die "usage: scripts/set-cap.sh <max desired capacity>"
bucket="$(stack_output PolicyBucket)"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
printf 'forbid (\n    principal,\n    action == Leash::Action::"scaleGroup",\n    resource\n) when { context.desiredCapacity > %s };\n' "$cap" > "$tmp"

log "validating the new policy against cedar/schema.json"
python -c '
import json, sys, cedarpy
text = open(sys.argv[1], encoding="utf-8").read()
schema = json.load(open(sys.argv[2], encoding="utf-8"))
res = cedarpy.validate_policies(text, schema)
if not res.validation_passed:
    print("INVALID:", [str(e) for e in res.errors]); sys.exit(1)
print("valid")
' "$tmp" "$REPO_ROOT/cedar/schema.json"

log "uploading ForbidScaleAboveCap.cedar (cap $cap) to s3://$bucket/cedar/policies/"
version="$(aws s3api put-object --bucket "$bucket" --key cedar/policies/ForbidScaleAboveCap.cedar \
  --body "$tmp" --content-type text/plain --query VersionId --output text)"
log "live. object version: $version"
log "try: scripts/ask.sh \"scale leash-dev-asg to $((cap + 1))\"  -> DENIED by ForbidScaleAboveCap"
log "previous versions: aws s3api list-object-versions --bucket $bucket --prefix cedar/policies/ForbidScaleAboveCap.cedar"
