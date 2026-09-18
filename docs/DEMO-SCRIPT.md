# Demo video — shot list (target 2:45, hard cap 3:00)

Judges score only the video and the repo. Record at 1080p, dashboard zoomed to ~125 % so the
ALLOW/DENY pills are readable on a phone. Pre-warm: deploy done, SNS email confirmed, prod instance
stopped, dashboard open in one browser tab, a terminal in the repo root, the email inbox in a
second tab. Run `scripts/ask.sh "hello"` once before recording so the Lambda is warm.

| Time | On screen | Voice-over |
| --- | --- | --- |
| 0:00–0:10 | Black screen, then a CloudWatch alarm in red: `leash-disk-dev — In alarm`. Clock overlay says 03:12. | "It's 3 AM. A disk is full, an alarm is red, and the fix is one command. Nobody is awake to run it — because nobody trusts a bot with the keys." |
| 0:10–0:25 | Title card: **Leash** — "an ops agent that can fix your AWS, but can never destroy anything". Team name. | "Leash is an AI ops agent on a leash. It fixes incidents on its own, but every single action is authorised by Cedar policies in Amazon Verified Permissions before it happens." |
| 0:25–0:45 | README architecture diagram, cursor tracing alarm -> EventBridge -> Agent Lambda -> Verified Permissions -> SSM/ECS/ASG -> DynamoDB -> SNS. | "An alarm goes through EventBridge to a Strands agent on Lambda, powered by Bedrock. The agent diagnoses with read-only tools. Before any mutating tool runs, it asks Verified Permissions. Allowed or denied, the decision lands in a DynamoDB audit trail and a summary is emailed." |
| 0:45–1:15 | **Beat 1.** Terminal: `scripts/break-disk.sh`. Cut to CloudWatch alarm flipping to ALARM. Cut to dashboard: a green `ALLOW cleanDisk` row with `PermitDevRemediation` appears. Cut to the email summary. | "Beat one. We fill the dev instance's disk past ninety percent. The alarm fires, the agent checks disk usage, and asks Cedar: may I clean the disk on a dev instance? Permit. It runs the cleanup over Systems Manager — no SSH — and emails what it did. Disk is back to normal." |
| 1:15–1:40 | **Beat 2.** Terminal: `scripts/kill-task.sh`. ECS console shows 0 running tasks, then dashboard shows `ALLOW restartService`, then ECS shows a new task RUNNING. | "Beat two. We kill the only task in the dev ECS service. Running count drops to zero, the alarm fires, the agent is allowed to force a new deployment, and nginx is back." |
| 1:40–2:15 | **Beat 3.** Dashboard "Ask the agent" box: type *Terminate the dev web instance*. Reply appears containing "DENIED by ForbidDestructive". A red `DENY terminateInstance` row appears. Then quickly: *Restart the prod db server* -> red row `ForbidProd`; *Scale leash-dev-asg to 10* -> red row `ForbidScaleAboveCap`. | "Beat three, the part that matters. We ask the agent to terminate the instance. It tries — the tool really exists — and Cedar says no: ForbidDestructive. We ask it to touch prod: ForbidProd. We ask it to scale to ten: ForbidScaleAboveCap. The model can be persuaded; the policy can't. And even if a policy were wrong, the Lambda's IAM role has an explicit deny on every delete API." |
| 2:15–2:35 | **Beat 4.** Full dashboard, slow scroll: green and red rows, policy ids, timestamps. Cut to `cedar/policies/` in the editor, the four short files. | "Every decision, allowed or denied, with the policy that made it, in one place. The whole leash is four Cedar policies you can read in a minute — and they are deployed with the rest of the stack in one SAM template." |
| 2:35–2:50 | Repo README on screen: deploy section, cost decisions. | "One `sam deploy` brings up the agent and the breakable infrastructure; one script tears it down. At rest it costs two micro instances and a quarter of a Fargate vCPU." |
| 2:50–2:58 | End card: **Leash** · github link · thegoodengineers · "Built with AWS, Strands, Cedar and Claude Code". | "Leash. Let the agent fix it — on a leash." |

Notes for the editor:

- `POST /ask` is synchronous behind a 30 s HTTP API timeout. Use it only for the fast prompts
  (terminate / prod / scale-to-10 denials and read-only questions). Never type "clean the disk"
  into the box on camera: the SSM cleanup can run up to 90 s and the request will time out even
  though the agent finishes and the ALLOW row still lands in the audit table. Beat 1 and Beat 2
  go through the alarm path (EventBridge -> Lambda), which has no such limit.

- Never show a screen for longer than ~8 s without a cut; keep the cursor moving.
- The denial in Beat 3 is the hero shot: hold on the red row and the policy id for a full 2 s.
- If the Bedrock reply is slow, cut around it; do not speed up the terminal.
- Mute system sounds; music under the voice-over at −20 dB.
