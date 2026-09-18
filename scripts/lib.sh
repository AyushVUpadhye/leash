#!/usr/bin/env bash
# Shared helpers for the Leash scripts. Source it, do not run it:
#   source "$(dirname "$0")/lib.sh"
#
# Every script resolves resource ids from the CloudFormation stack outputs so
# nothing is hard-coded except the stack name and region.

STACK_NAME="${STACK_NAME:-leash}"
AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
export AWS_REGION AWS_DEFAULT_REGION="$AWS_REGION"
# Keep the AWS CLI from opening a pager for every call.
export AWS_PAGER=""

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() { printf '[leash] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

# stack_output <OutputKey> -> prints the output value or fails.
# https://docs.aws.amazon.com/cli/latest/reference/cloudformation/describe-stacks.html
stack_output() {
  local key="$1" value
  value="$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" --region "$AWS_REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='${key}'].OutputValue | [0]" \
    --output text)"
  if [[ -z "$value" || "$value" == "None" ]]; then
    die "stack output '$key' not found on stack '$STACK_NAME' (is it deployed?)"
  fi
  printf '%s' "$value"
}

require_cmd() {
  local c
  for c in "$@"; do
    command -v "$c" >/dev/null 2>&1 || die "'$c' is required but not on PATH"
  done
}
