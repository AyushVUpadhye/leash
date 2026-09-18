#!/usr/bin/env bash
# Stop the prod decoy instance (leash-prod-db) right after deploy.
#
#   scripts/stop-prod.sh
#
# CloudFormation cannot create an instance in the stopped state, so it boots
# once and we stop it here. A stopped instance keeps its tags, so the agent can
# still be asked to touch it and Cedar (ForbidProd) can still deny it - at
# zero compute cost.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_cmd aws

instance_id="$(stack_output ProdInstanceId)"
state="$(aws ec2 describe-instances --instance-ids "$instance_id" \
  --query 'Reservations[0].Instances[0].State.Name' --output text)"
log "prod instance $instance_id is currently: $state"

if [[ "$state" == "stopped" ]]; then
  log "already stopped, nothing to do"
  exit 0
fi

log "stopping $instance_id"
aws ec2 stop-instances --instance-ids "$instance_id" \
  --query 'StoppingInstances[0].CurrentState.Name' --output text
log "waiting until stopped"
aws ec2 wait instance-stopped --instance-ids "$instance_id"
log "done: $instance_id is stopped (tags env=prod, Name=leash-prod-db are kept)"
