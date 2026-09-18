#!/usr/bin/env bash
# Build and deploy the Leash stack, then publish the dashboard.
#
#   scripts/deploy.sh            # guided on first run, non-interactive after
#   scripts/deploy.sh --guided   # force the guided prompts again
#
# First run asks for AlertEmail, VpcId, SubnetId (use the default VPC and one
# of its public subnets) and saves them to samconfig.toml. After the stack is
# up it writes dashboard/config.js from the ApiUrl output and syncs dashboard/
# to the public website bucket. Remember to run scripts/stop-prod.sh afterwards.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_cmd sam aws

cd "$REPO_ROOT"

log "building the Linux dependency layer (scripts/build-deps.sh)"
bash "$(dirname "$0")/build-deps.sh"
log "building (sam build)"
sam build

# samconfig.toml gets parameter_overrides only after a guided deploy has run.
if [[ "${1:-}" == "--guided" ]] || ! grep -q '^parameter_overrides' samconfig.toml; then
  log "first deploy: running 'sam deploy --guided' (answers are saved to samconfig.toml)"
  sam deploy --guided --stack-name "$STACK_NAME" --region "$AWS_REGION" \
    --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND --resolve-s3
else
  log "deploying stack '$STACK_NAME' in $AWS_REGION"
  sam deploy --no-confirm-changeset --no-fail-on-empty-changeset
fi

api_url="$(stack_output ApiUrl)"
bucket="$(stack_output DashboardBucket)"
dashboard_url="$(stack_output DashboardUrl)"

log "writing dashboard/config.js with apiUrl=$api_url"
mkdir -p dashboard
printf 'window.LEASH_CONFIG = { apiUrl: "%s" };\n' "$api_url" > dashboard/config.js

log "syncing dashboard/ to s3://$bucket"
aws s3 sync dashboard/ "s3://$bucket/" --delete

log "done"
log "  API:       $api_url"
log "  Dashboard: $dashboard_url"
log "  Confirm the SNS subscription email, then run scripts/stop-prod.sh"
