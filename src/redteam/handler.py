"""Lambda entry point for the red-team arena.

Event: {"n": 20, "arms": ["leashed", "unleashed"], "run_id": "...", "use_model": true}
Runs up to MAX_PER_INVOCATION attacks in this invocation, writes one row per attack, and
returns {"run_id", "rows": <count>, "summary"}. Larger n is chained: the function invokes itself
asynchronously with the remainder, so 300 attacks never hit the 15-minute limit.

Resource ids come from the environment (deploy-time stack outputs) so every attack names real
resources in this account.
"""

from __future__ import annotations

import json
import logging
import os

from redteam import attacks as attacks_mod, runner

log = logging.getLogger("leash.redteam.handler")
log.setLevel(logging.INFO)

MAX_PER_INVOCATION = int(os.environ.get("REDTEAM_MAX_PER_INVOCATION", "12"))


def resource_ids() -> dict:
    return {
        "dev": os.environ.get("DEV_INSTANCE_ID", "i-0de70000000000001"),
        "prod": os.environ.get("PROD_INSTANCE_ID", "i-0a0d0000000000001"),
        "asg": os.environ.get("ASG_NAME", "leash-dev-asg"),
        "big": os.environ.get("REDTEAM_BIG", "10"),
    }


def _chain(event: dict) -> None:
    """Invoke this function again, asynchronously, with the remaining attacks."""
    import boto3

    name = os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
    if not name:
        return
    boto3.client("lambda").invoke(FunctionName=name, InvocationType="Event",
                                  Payload=json.dumps(event).encode("utf-8"))


def handler(event, context):
    event = event or {}
    n = max(1, min(int(event.get("n", 20)), 500))
    arms = tuple(event.get("arms") or ("leashed", "unleashed"))
    run_id = event.get("run_id") or runner._now_id()
    start = int(event.get("start", 0))
    use_model = bool(event.get("use_model", True))
    seed = event.get("seed")

    catalogue = attacks_mod.build_catalogue(resource_ids(), n, use_model=use_model, seed=seed)
    this_batch = catalogue[start:start + MAX_PER_INVOCATION]
    log.info("red-team run %s: attacks %d..%d of %d, arms=%s", run_id, start, start + len(this_batch), n, arms)

    rows = runner.run_batch(this_batch, run_id=run_id, arms=arms, start_index=start)
    remaining = n - (start + len(this_batch))
    if remaining > 0:
        _chain({**event, "run_id": run_id, "start": start + len(this_batch), "n": n, "seed": seed or 0})
    summary = runner.summarise(rows)
    log.info("red-team batch done: %s", json.dumps(summary)[:1500])
    return {"run_id": run_id, "rows": len(rows), "remaining": max(0, remaining), "summary": summary}
