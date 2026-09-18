#!/usr/bin/env bash
# Demo beat 2: the nginx service loses its only task and nothing replaces it.
#
#   scripts/kill-task.sh
#
# Simply stopping the task is not enough for a demo: the ECS scheduler replaces it
# within seconds and Container Insights samples RunningTaskCount once a minute, so
# the alarm never sees a zero. This script stops the task AND sets the service's
# desired count to 0, which is what a service looks like after a bad deploy or an
# operator mistake. RunningTaskCount drops to 0, leash-ecs-dev fires, and the
# agent's restart_service (allowed by PermitDevRemediation on env=dev) sets the
# desired count back to 1 and forces a new deployment. Nothing recovers on its own.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_cmd aws

cluster="$(stack_output EcsClusterName)"
service="$(stack_output EcsServiceName)"
log "taking $service in cluster $cluster down: desired count -> 0"
# https://docs.aws.amazon.com/cli/latest/reference/ecs/update-service.html
aws ecs update-service --cluster "$cluster" --service "$service" --desired-count 0 \
  --query 'service.[desiredCount,runningCount]' --output text
for arn in $(aws ecs list-tasks --cluster "$cluster" --service-name "$service" \
    --desired-status RUNNING --query 'taskArns' --output text 2>/dev/null); do
  [[ -n "$arn" && "$arn" != "None" ]] || continue
  aws ecs stop-task --cluster "$cluster" --task "$arn" --reason "leash demo: simulated crash" \
    --query 'task.lastStatus' --output text >/dev/null && log "stopped ${arn##*/}"
done
log "leash-ecs-dev should enter ALARM within ~1-2 minutes; the agent's restart_service brings it back"
