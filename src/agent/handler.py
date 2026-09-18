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


def build_alarm_prompt(parsed: dict) -> str:
    dims = json.dumps(parsed["dimensions"], sort_keys=True)
    return (
        f"CloudWatch alarm '{parsed['alarm_name']}' entered state {parsed['state']}.\n"
        f"Metric dimensions: {dims}\n"
        "Diagnose the resource named by the dimensions (InstanceId -> EC2 disk; ClusterName + "
        "ServiceName -> ECS service), confirm its env tag, then remediate through the tools. "
        "Finish with a one-paragraph summary."
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
