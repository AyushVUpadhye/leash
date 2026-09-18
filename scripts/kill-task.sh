#!/usr/bin/env bash
# Demo beat 2: crash-loop the nginx task of leash-api-dev so RunningTaskCount stays
# below 1 long enough for leash-ecs-dev to fire.
#
#   scripts/kill-task.sh [seconds]     # default 150
#
# ECS replaces a stopped task within seconds, and Container Insights samples
# RunningTaskCount once a minute, so a single stop is usually never seen by the
# alarm. Stopping every new task for a couple of minutes simulates a container
# that keeps crashing; the alarm fires, the agent's restart_service forces a
# fresh deployment, and once this script stops killing, the service recovers.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_cmd aws

duration="${1:-150}"
cluster="$(stack_output EcsClusterName)"
service="$(stack_output EcsServiceName)"
log "crash-looping $service in cluster $cluster for ${duration}s"

end=$(( $(date +%s) + duration ))
killed=0
while [ "$(date +%s)" -lt "$end" ]; do
  for arn in $(aws ecs list-tasks --cluster "$cluster" --service-name "$service" \
      --desired-status RUNNING --query 'taskArns' --output text 2>/dev/null); do
    [[ -n "$arn" && "$arn" != "None" ]] || continue
    # https://docs.aws.amazon.com/cli/latest/reference/ecs/stop-task.html
    aws ecs stop-task --cluster "$cluster" --task "$arn" --reason "leash demo: simulated crash" \
      --query 'task.lastStatus' --output text >/dev/null 2>&1 && killed=$((killed + 1)) && log "stopped ${arn##*/}"
  done
  sleep 10
done
log "stopped $killed task(s) in ${duration}s; leash-ecs-dev should be in ALARM and the agent queued"
