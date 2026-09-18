"""Authorisation for every Leash action: ask Cedar before touching anything.

Default mode calls Amazon Verified Permissions (IsAuthorized) on the policy store in
POLICY_STORE_ID. With LEASH_LOCAL_AUTHZ="1" the same request is evaluated locally with
cedarpy against cedar/policies/*.cedar + cedar/schema.json (tests, offline demo).

Either way the answer is a Decision and any failure is a DENY ("authz-error: ...").
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

NAMESPACE = "Leash"
PRINCIPAL_ID = "leash"
RESOURCE_TYPES = ("Instance", "EcsService", "AutoScalingGroup")
POLICY_NAMES = ("PermitDevRemediation", "ForbidDestructive", "ForbidProd", "ForbidScaleAboveCap")

_AVP = None  # cached boto3 client
_LOCAL: dict = {}  # cached cedarpy inputs: {"policies", "schema", "dir"}


@dataclass
class Decision:
    """Outcome of one authorisation request (allowed, which policies decided, why)."""

    allowed: bool
    policy_ids: list = field(default_factory=list)
    reason: str = ""
    errors: list = field(default_factory=list)


def authorize(action: str, resource_type: str, resource_id: str, resource_env: str,
              context: dict | None = None) -> Decision:
    """Is Leash::Agent::"leash" allowed to perform `action` on this resource?

    resource_type is "Instance" | "EcsService" | "AutoScalingGroup" (no namespace).
    Fails closed: any exception becomes Decision(allowed=False, reason="authz-error: ...").
    """
    try:
        if resource_type not in RESOURCE_TYPES:
            raise ValueError(f"unknown resource_type {resource_type!r}")
        if os.environ.get("LEASH_LOCAL_AUTHZ") == "1":
            return _authorize_local(action, resource_type, resource_id, resource_env, context or {})
        return _authorize_avp(action, resource_type, resource_id, resource_env, context or {})
    except Exception as exc:  # noqa: BLE001 - fail closed, whatever went wrong
        return Decision(allowed=False, policy_ids=[], reason=f"authz-error: {exc}", errors=[str(exc)])


# --- Amazon Verified Permissions ------------------------------------------------


def _avp_client():
    global _AVP
    if _AVP is None:
        import boto3

        _AVP = boto3.client("verifiedpermissions", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _AVP


def _avp_value(value):
    """Type a Python value the way the Verified Permissions API wants it ({"long": 4} etc.)."""
    if isinstance(value, bool):
        return {"boolean": value}
    if isinstance(value, int):
        return {"long": value}
    if isinstance(value, str):
        return {"string": value}
    raise TypeError(f"unsupported context value type {type(value).__name__}")


def _policy_names() -> dict:
    """AVP policy id -> logical name, from POLICY_ID_MAP (cedar/template.yaml output PolicyIdMap)."""
    raw = os.environ.get("POLICY_ID_MAP", "")
    if not raw:
        return {}
    return {pid: name for name, pid in json.loads(raw).items()}


def _authorize_avp(action, resource_type, resource_id, resource_env, context) -> Decision:
    # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/verifiedpermissions/client/is_authorized.html
    entity_type = f"{NAMESPACE}::{resource_type}"
    resp = _avp_client().is_authorized(
        policyStoreId=os.environ["POLICY_STORE_ID"],
        principal={"entityType": f"{NAMESPACE}::Agent", "entityId": PRINCIPAL_ID},
        action={"actionType": f"{NAMESPACE}::Action", "actionId": action},
        resource={"entityType": entity_type, "entityId": resource_id},
        context={"contextMap": {k: _avp_value(v) for k, v in context.items()}},
        entities={"entityList": [
            {"identifier": {"entityType": f"{NAMESPACE}::Agent", "entityId": PRINCIPAL_ID},
             "attributes": {}, "parents": []},
            {"identifier": {"entityType": entity_type, "entityId": resource_id},
             "attributes": {"env": {"string": resource_env}}, "parents": []},
        ]},
    )
    names = _policy_names()
    raw_ids = [p.get("policyId", "") for p in resp.get("determiningPolicies", [])]
    policy_ids = [names.get(pid, pid) for pid in raw_ids]
    errors = [e.get("errorDescription", "") for e in resp.get("errors", [])]
    allowed = resp.get("decision") == "ALLOW"
    return Decision(allowed=allowed, policy_ids=policy_ids, reason=_reason(allowed, policy_ids, "avp"), errors=errors)


# --- local evaluation with cedarpy --------------------------------------------------


def cedar_dir() -> Path:
    """cedar/ directory: LEASH_CEDAR_DIR, else the repo's cedar/ next to src/."""
    override = os.environ.get("LEASH_CEDAR_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "cedar"


def _load_local() -> dict:
    """Read the four policies (with an in-memory @id so diagnostics name them) and the schema."""
    base = cedar_dir()
    if _LOCAL.get("dir") != base:
        parts = []
        for name in POLICY_NAMES:
            text = (base / "policies" / f"{name}.cedar").read_text(encoding="utf-8")
            parts.append(f'@id("{name}")\n{text}')
        _LOCAL.update(dir=base, policies="\n".join(parts),
                      schema=json.loads((base / "schema.json").read_text(encoding="utf-8")))
    return _LOCAL


def _authorize_local(action, resource_type, resource_id, resource_env, context) -> Decision:
    # cedarpy 4.x: is_authorized(request, policies, entities, schema) -> AuthzResult;
    # diagnostics.reasons are parser ids ("policy0"), id_annotations_by_reason maps them to @id.
    import cedarpy

    local = _load_local()
    entity_type = f"{NAMESPACE}::{resource_type}"
    request = {
        "principal": {"type": f"{NAMESPACE}::Agent", "id": PRINCIPAL_ID},
        "action": {"type": f"{NAMESPACE}::Action", "id": action},
        "resource": {"type": entity_type, "id": resource_id},
        "context": dict(context),
    }
    entities = [
        {"uid": {"type": f"{NAMESPACE}::Agent", "id": PRINCIPAL_ID}, "attrs": {}, "parents": []},
        {"uid": {"type": entity_type, "id": resource_id}, "attrs": {"env": resource_env}, "parents": []},
    ]
    result = cedarpy.is_authorized(request, local["policies"], entities, local["schema"])
    names = result.diagnostics.id_annotations_by_reason
    policy_ids = [names.get(r, r) for r in result.diagnostics.reasons]
    allowed = result.allowed
    return Decision(allowed=allowed, policy_ids=policy_ids, reason=_reason(allowed, policy_ids, "local"),
                    errors=list(result.diagnostics.errors))


def _reason(allowed: bool, policy_ids: list, mode: str) -> str:
    if allowed:
        return f"permit by {', '.join(policy_ids)} ({mode})"
    if policy_ids:
        return f"forbid by {', '.join(policy_ids)} ({mode})"
    return f"no permit policy matched; Cedar denies by default ({mode})"
