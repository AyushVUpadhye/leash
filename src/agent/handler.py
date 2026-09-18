"""Lambda entry point for the Leash agent.

Handles two event shapes:
  1. EventBridge "CloudWatch Alarm State Change" (source aws.cloudwatch) -> diagnose + remediate.
  2. Direct invoke {"mode": "chat", "message": "..."} -> answer a human, tools still leashed.
Returns {"reply": <agent text>, "incident_id": <id>} in both cases.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone

from agent import tools
from agent.agent import SYSTEM_PROMPT, build_agent

log = logging.getLogger("leash.handler")
log.setLevel(logging.INFO)

# One Agent per warm container; system prompt and history are reset per invocation.
_AGENT = None


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-") or "alarm"


def parse_event(event: dict) -> dict:
    """Normalise both event shapes into {"mode", "alarm_name", "state", "dimensions", "message"}.

    Dimensions come from detail.configuration.metrics[i].metricStat.metric.dimensions (a
    name->value dict), merged across metrics; alarm name is only a hint.
    Event format: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/cloudwatch-and-eventbridge.html
    """
    if event.get("mode") == "chat" or "message" in event and "source" not in event:
        return {"mode": "chat", "alarm_name": "", "state": "", "dimensions": {},
                "message": str(event.get("message", "")).strip()}
    if event.get("source") == "aws.cloudwatch":
        detail = event.get("detail", {}) or {}
        dims: dict = {}
        for metric in (detail.get("configuration", {}) or {}).get("metrics", []) or []:
            found = ((metric.get("metricStat") or {}).get("metric") or {}).get("dimensions") or {}
            dims.update({str(k): str(v) for k, v in found.items()})
        return {"mode": "alarm", "alarm_name": detail.get("alarmName", ""),
                "state": (detail.get("state") or {}).get("value", ""), "dimensions": dims, "message": ""}
    return {"mode": "unknown", "alarm_name": "", "state": "", "dimensions": {}, "message": ""}


def _runbook(dimensions: dict) -> str:
    """Pick the explicit runbook for this alarm from its dimensions.

    The whole point of Leash is that the fix for these alarms is a known, boring step. Spelling
    it out keeps small local models (llama3.2:3b in local_demo/) from improvising - e.g. scaling
    a group to "fix" a full disk. Cedar still decides whether any step is allowed.
    """
    if "InstanceId" in dimensions:
        iid = dimensions["InstanceId"]
        return (
            "Runbook (disk alarm on an EC2 instance):\n"
            f"  1. get_instance_info('{iid}') to confirm the env tag.\n"
            f"  2. get_disk_usage('{iid}') to confirm usage is high.\n"
            f"  3. clean_disk('{iid}') - this is the ONLY correct remediation for a disk alarm.\n"
            f"  4. get_disk_usage('{iid}') again to confirm it dropped.\n"
            "  Do NOT call scale_group, restart_service or terminate_instance for a disk alarm."
        )
    if "ClusterName" in dimensions and "ServiceName" in dimensions:
        cluster, service = dimensions["ClusterName"], dimensions["ServiceName"]
        return (
            "Runbook (ECS service has no running tasks):\n"
            f"  1. get_service_info('{cluster}', '{service}') to confirm running < desired and the env tag.\n"
            f"  2. restart_service('{cluster}', '{service}') - this is the ONLY correct remediation.\n"
            f"  3. get_service_info('{cluster}', '{service}') again to confirm running count recovered.\n"
            "  Do NOT call scale_group, clean_disk or terminate_instance for an ECS alarm."
        )
    return (
        "No runbook matches these dimensions. Use the read-only tools to investigate and report; "
        "do not change anything."
    )


def build_alarm_prompt(parsed: dict) -> str:
    dims = json.dumps(parsed["dimensions"], sort_keys=True)
    return (
        f"CloudWatch alarm '{parsed['alarm_name']}' entered state {parsed['state']}.\n"
        f"Metric dimensions: {dims}\n\n"
        f"{_runbook(parsed['dimensions'])}\n\n"
        "Follow the runbook step by step, calling each tool with exactly the ids above. If any "
        "tool returns DENIED, stop, report the denial verbatim with its policy ids, and do not try "
        "another action. Finish with a one-paragraph summary: what was wrong, what you did, "
        "current state."
    )


def _get_agent(incident_id: str):
    global _AGENT
    if _AGENT is None:
        _AGENT = build_agent(incident_id)
    else:
        _AGENT.messages = []
        _AGENT.system_prompt = SYSTEM_PROMPT.format(
            incident_id=incident_id, scale_cap=os.environ.get("SCALE_CAP", "4")
        )
    return _AGENT


def handler(event, context):
    """Lambda handler; never raises for a bad event, always returns a reply dict."""
    log.info("event: %s", json.dumps(event)[:2000])
    parsed = parse_event(event)
    ts = _timestamp()

    if parsed["mode"] == "chat":
        incident_id = f"chat-{ts}"
        if not parsed["message"]:
            return {"reply": "empty message", "incident_id": incident_id}
        tools.set_context(incident_id, "")
        prompt = f"A human operator asks: {parsed['message']}"
    elif parsed["mode"] == "alarm":
        incident_id = f"{_slug(parsed['alarm_name'])}-{ts}"
        if parsed["state"] != "ALARM":
            return {"reply": f"ignored: state {parsed['state']!r} is not ALARM", "incident_id": incident_id}
        tools.set_context(incident_id, parsed["alarm_name"])
        prompt = build_alarm_prompt(parsed)
    else:
        return {"reply": "ignored: unrecognised event shape", "incident_id": f"unknown-{ts}"}

    try:
        agent = _get_agent(incident_id)
        reply = str(agent(prompt)).strip()
    except Exception as exc:
        log.exception("agent run failed")
        reply = f"agent error: {exc}"

    if parsed["mode"] == "alarm":
        # Always send the summary for alarms, even if the model forgot to call notify itself.
        log.info("notify: %s", tools.notify(f"Incident {incident_id}\n\n{reply}"))

    log.info("reply: %s", reply[:2000])
    return {"reply": reply, "incident_id": incident_id}
