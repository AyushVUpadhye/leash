#!/usr/bin/env bash
# Demo beat 2: stop the running nginx task of leash-api-dev so RunningTaskCount
# drops below 1 and leash-ecs-dev fires. ECS will also replace the task on its
# own; the agent's restart_service tool forces a fresh deployment on top.
#
#   scripts/kill-task.sh
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_cmd aws

cluster="$(stack_output EcsClusterName)"
service="$(stack_output EcsServiceName)"
log "looking up running tasks for $service in cluster $cluster"

task_arn="$(aws ecs list-tasks --cluster "$cluster" --service-name "$service" \
  --desired-status RUNNING --query 'taskArns[0]' --output text)"
[[ -n "$task_arn" && "$task_arn" != "None" ]] || die "no running task found for $service"

log "stopping task $task_arn"
# https://docs.aws.amazon.com/cli/latest/reference/ecs/stop-task.html
aws ecs stop-task --cluster "$cluster" --task "$task_arn" \
  --reason "leash demo: simulated crash" \
  --query 'task.{arn:taskArn,status:lastStatus}' --output table
log "leash-ecs-dev should enter ALARM within ~1-2 minutes; watch the dashboard"
