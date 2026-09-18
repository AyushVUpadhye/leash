#!/usr/bin/env bash
# Delete everything: empty the dashboard bucket (CloudFormation refuses to
# delete a non-empty bucket), then `sam delete` the stack, nested Authz app
# included. Stopped instances are terminated by CloudFormation as usual.
#
#   scripts/teardown.sh
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_cmd sam aws

cd "$REPO_ROOT"

if bucket="$(stack_output DashboardBucket 2>/dev/null)"; then
  log "emptying s3://$bucket"
  aws s3 rm "s3://$bucket/" --recursive || log "bucket already empty or gone"
else
  log "no DashboardBucket output found; skipping bucket cleanup"
fi

log "deleting stack '$STACK_NAME' in $AWS_REGION (sam delete)"
sam delete --stack-name "$STACK_NAME" --region "$AWS_REGION" --no-prompts

rm -f dashboard/config.js
log "done"
