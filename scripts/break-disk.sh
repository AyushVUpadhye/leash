#!/usr/bin/env bash
# Demo beat 1: fill the dev instance's root disk so leash-disk-dev fires.
#
#   scripts/break-disk.sh [target_percent]     # default 92
#
# Uses SSM Run Command (no SSH). The size is computed ON the instance from df,
# so it works whatever the disk size is. The agent's clean_disk tool removes
# /var/tmp/leash-fill* again.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_cmd aws

target="${1:-92}"
instance_id="$(stack_output DevInstanceId)"
log "filling / on $instance_id to ${target}% used"

# Shell script that runs on the instance. Fills with fallocate (instant, no IO).
remote_script=$(cat <<EOF
set -eu
read -r total used avail <<<"\$(df -k / | awk 'NR==2{print \$2, \$3, \$4}')"
want=\$(( total * ${target} / 100 ))
fill_kb=\$(( want - used ))
# never ask for more than is actually available (xfs keeps some blocks back)
max_kb=\$(( avail - 262144 ))
if [ "\$fill_kb" -gt "\$max_kb" ]; then fill_kb=\$max_kb; fi
if [ "\$fill_kb" -le 0 ]; then echo "already above ${target}%"; df -h /; exit 0; fi
echo "total=\${total}K used=\${used}K avail=\${avail}K -> allocating \${fill_kb}K"
rm -f /var/tmp/leash-fill-1
# /var/tmp, not /tmp: on AL2023 /tmp is a RAM-backed tmpfs and would not fill "/" at all.
fallocate -l "\${fill_kb}K" /var/tmp/leash-fill-1
df -h /
EOF
)

# Build the SSM parameters JSON with python so quoting is exact (no jq dependency). Passed
# inline rather than via file:// so it also works from Git Bash on Windows.
params="$(python -c 'import json, sys; print(json.dumps({"commands": sys.argv[1].splitlines()}))' "$remote_script")"

# https://docs.aws.amazon.com/cli/latest/reference/ssm/send-command.html
command_id="$(aws ssm send-command \
  --document-name AWS-RunShellScript \
  --instance-ids "$instance_id" \
  --comment "leash demo: fill disk" \
  --parameters "$params" \
  --query 'Command.CommandId' --output text)"
log "sent SSM command $command_id, waiting for it to finish"

for _ in $(seq 1 30); do
  status="$(aws ssm get-command-invocation --command-id "$command_id" \
    --instance-id "$instance_id" --query Status --output text 2>/dev/null || echo Pending)"
  case "$status" in
    Success|Failed|Cancelled|TimedOut) break ;;
  esac
  sleep 2
done

log "status: $status"
aws ssm get-command-invocation --command-id "$command_id" --instance-id "$instance_id" \
  --query '[StandardOutputContent, StandardErrorContent]' --output text
log "leash-disk-dev should enter ALARM within ~30 s; watch the dashboard"
