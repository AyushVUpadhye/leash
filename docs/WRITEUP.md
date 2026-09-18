# Leash — submission writeup

**Team:** thegoodengineers · **Track:** Ship It · **Event:** First Commit, WeMakeDevs x AWS, 17–20 Sept 2026

## The problem

Every small team has the same 3 AM story: a disk fills up or a container dies, an alarm fires, and
the fix is a step everyone already knows. Nobody automates it because the only tool that could do
the fix on its own — an AI agent with cloud credentials — could also delete the database, and a
single crafted log line or chat message can talk a model into doing exactly that. Trust is the
blocker, not capability.

## What we built

Leash is a Strands agent running in AWS Lambda that receives CloudWatch alarm events, diagnoses
the resource, and runs the remediation: clean a full disk over SSM, force a new ECS deployment,
or scale an Auto Scaling group. The twist is that the agent has no direct power. Every mutating
tool first asks **Amazon Verified Permissions** whether the action is allowed, using four Cedar
policies: remediation is permitted only on resources tagged `env=dev`; terminate and delete are
forbidden for everyone; anything tagged `env=prod` is forbidden; and scaling above four instances
is forbidden. Cedar is deny-by-default and forbid beats permit, so no prompt can widen the leash.
Each decision — ALLOW or DENY, with the policy ids that fired — is written to a DynamoDB audit
table, a summary goes out over SNS, and a small dashboard shows the trail live. A `/ask` endpoint
lets a human ask the agent to do something dangerous so the denial can be watched in real time.

## Where AWS fits

CloudWatch and EventBridge turn an alarm into an event; Lambda runs the agent only while an
incident exists; Bedrock hosts the model with IAM auth and no keys; Verified Permissions evaluates
the policies outside the model's reach; Systems Manager lets us fix an instance with no SSH and no
open ports; ECS on Fargate and Auto Scaling are the things being fixed; DynamoDB, SNS, API
Gateway and S3 give the audit trail somewhere to live. IAM sits underneath Cedar as a second,
independent floor with explicit denies on every destructive API. One SAM template deploys all of
it, including the deliberately breakable infrastructure, and one script tears it down.
