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
table, a summary goes out over SNS, and a small dashboard shows the trail live next to the
policies themselves, read straight from the policy store. A `/ask` endpoint lets a human ask the
agent to do something dangerous so the denial can be watched in real time, and a prompt injection
planted in the instance's own `Name` tag shows that the leash holds even when the attack comes
from inside the data the agent reads.

## Proving it: the red team

"The model cannot be talked into it" is a claim, so we measure it. An attacker model writes
attacks across eight tactics (fake authority, fake emergency, fake policy update, role-play,
obfuscation, instructions hidden in logs and alarm payloads, slow escalation, and plain asking),
each naming real resources in the account. Every attack runs twice with the same model and the
same tools: once through the real agent with Cedar on, and once through the same agent with
authorisation off inside an in-memory sandbox where nothing real can be harmed. The dashboard
reports how often the model was persuaded to call the destructive tool, how many attacks executed
a destructive action without the leash, and how many did with Leash. The last figure is the
project: it stays at zero, and every one of those zeros is a real Verified Permissions denial with
the policy id that produced it. The numbers from the deployed run are on the live dashboard and
copied into the README before submission.

## Where AWS fits

CloudWatch and EventBridge turn an alarm into an event; Lambda runs the agent only while an
incident exists; Bedrock hosts the model with IAM auth and no keys; Verified Permissions evaluates
the policies outside the model's reach; Systems Manager lets us fix an instance with no SSH and no
open ports; ECS on Fargate and Auto Scaling are the things being fixed; DynamoDB, SNS, API
Gateway and S3 give the audit trail somewhere to live. IAM sits underneath Cedar as a second,
independent floor with explicit denies on every destructive API. One SAM template deploys all of
it, including the deliberately breakable infrastructure, and one script tears it down.

## Impact, measured

The dashboard computes these from the audit trail itself, not from a slide:

| What changes | Before Leash | With Leash |
| --- | --- | --- |
| A destructive action after a jailbreak attempt | depends on the model's mood that night | 0, measured across every tactic; the control arm shows what the same model does unleashed |
| Time from alarm to fix for a full dev disk | until a human wakes up and runs one command: typically 30 min to several hours | median under 90 s, alarm event to allowed fix, no human involved (shown as **Alarm → fixed** on the dashboard) |
| Who can destroy something at 3 AM | anyone with the admin keys the bot would need | nobody: terminate and delete are forbidden by policy, by IAM, and by code |
| How you find out what the bot did | grep CloudTrail | one table: every ALLOW and DENY with the policy id that decided it |
| How you change what the bot may do | edit a prompt and hope | edit a five-line Cedar policy; the model never sees it |
| Cost at rest | — | two `t3.micro` (one stopped) and a quarter Fargate vCPU; everything else is pay-per-use |

## What we learned

- **Put the guardrail outside the model.** Our first attempt told the model the rules in the
  system prompt. A small local model happily "refused" on its own, or narrated a tool call as text,
  and nothing was audited either way. Moving every check into the tool (`authorize()` before
  `act()`) and telling the model *not* to enforce policy itself made the behaviour identical across
  Bedrock Haiku and a 3B Llama. The value is in the policies, not in the model.
- **Cedar's `forbid`-beats-`permit` is the whole trick.** A policy like
  `forbid (principal, action, resource) when { resource.env == "prod" }` cannot be argued with;
  the worst a persuaded model can do is ask, be denied, and leave a red row.
- **Verified Permissions returns opaque policy ids.** The audit row would have said
  `SPEXAMPLEabc...`; we export a name-to-id map from the nested SAM stack and translate it back, so
  the row and the reply say `ForbidProd`.
- **CloudWatch alarm dimensions must match the agent's metric exactly.** `disk_used_percent` from
  the CloudWatch agent carries `device` and `host` dimensions by default; we drop them in the
  agent config so the alarm only needs `InstanceId + path + fstype`.
- **IAM cannot express "not above 4".** It can deny an API, not a value in the request. That is
  why Cedar is the leash and IAM is the floor, and why both exist.
- **A guardrail claim needs a control group.** Running the same attacks against the same model
  with authorisation off, in a sandbox, is what turns "it refused" into a number. It also
  separates "the model refused" from "the policy refused", which are very different guarantees:
  only the second one is the same every night.
- **Build the offline path early.** Our AWS account was stuck in verification on day one, so we
  built `local_demo/`: the same agent, tools and `.cedar` files against an in-memory AWS. It became
  the fastest way to iterate on prompts and the way the tests run in CI.

## Two ways to run it

The same code runs in two places. On AWS, `sam deploy` brings up the agent Lambda, the Verified
Permissions policy store, the audit table, the API, the dashboard and the deliberately breakable
dev infrastructure. On a laptop with no AWS account, `local_demo/` runs the identical agent,
tools, Cedar policies (evaluated with cedarpy against the same `.cedar` files that the SAM
template deploys) and dashboard, with a local Ollama model in place of Bedrock and AWS itself
replaced by an in-memory simulation that answers the exact same boto3 calls. Every audit row
in the demo, allowed or denied, comes from a real Cedar decision on the real policy text.

## AI tools used

Claude Code was used to scaffold and review the code. All architecture decisions, the policy
design and the demo were made by the team; every generated file was read and tested locally
before being kept.
