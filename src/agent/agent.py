"""Builds the Strands agent for Leash: Bedrock model + tools + a short, explicit system prompt."""

import os

# Verified against strands-agents 1.56.0: strands.Agent(model=, tools=, system_prompt=,
# callback_handler=None) and strands.models.BedrockModel(model_id=, region_name=).
from strands import Agent
from strands.models import BedrockModel

from agent import tools

DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

SYSTEM_PROMPT = """You are Leash, an on-call operations agent for a small AWS account.

Rules:
1. Diagnose first: use the read-only tools (get_instance_info, get_disk_usage, get_service_info)
   to confirm the problem and learn the resource's env tag before changing anything.
2. Act only through the tools. Never describe an action as done unless a tool returned ALLOWED
   and a success result. If a tool returns "DENIED by ...", report the denial verbatim including the
   policy ids and stop trying that action; do not look for workarounds.
3. Every mutating action is checked against Cedar policies in Amazon Verified Permissions. You may
   only remediate resources tagged env=dev, you may never terminate or delete anything, and you may
   never scale a group above {scale_cap} instances. If a human asks for something outside those
   limits, still call the tool once so the denial is audited, then explain the denial.
4. Be brief. Finish with one paragraph: what was wrong, what you did (or were denied), current state.

Incident id: {incident_id}
"""


def build_agent(incident_id: str) -> Agent:
    """Return a fresh Strands Agent for this incident."""
    model = BedrockModel(
        model_id=os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        max_tokens=2048,
    )
    prompt = SYSTEM_PROMPT.format(incident_id=incident_id, scale_cap=os.environ.get("SCALE_CAP", "4"))
    # callback_handler=None disables the streaming stdout printer; the handler logs the final text.
    return Agent(model=model, tools=tools.ALL_TOOLS, system_prompt=prompt, callback_handler=None)
