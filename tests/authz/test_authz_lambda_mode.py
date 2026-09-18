"""LEASH_AUTHZ_FUNCTION: authorize() asks the authorizer Lambda and carries its audit_ref."""

import io
import json

import pytest

import common.authz as authz


class FakeLambda:
    def __init__(self, reply=None, function_error=None):
        self.calls = []
        self.reply = reply if reply is not None else {
            "allowed": False, "policy_ids": ["ForbidProd"], "reason": "forbid by ForbidProd (local)",
            "errors": [], "audit_ref": {"pk": "inc-7", "sk": "2026-09-19T00:00:00.000001Z"}}
        self.function_error = function_error

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        resp = {"Payload": io.BytesIO(json.dumps(self.reply).encode())}
        if self.function_error:
            resp["FunctionError"] = self.function_error
        return resp


@pytest.fixture
def via_lambda(monkeypatch):
    fake = FakeLambda()
    monkeypatch.setenv("LEASH_AUTHZ_FUNCTION", "leash-authz")
    monkeypatch.delenv("LEASH_LOCAL_AUTHZ", raising=False)
    monkeypatch.setattr(authz, "_lambda_client", lambda: fake)
    return fake


def test_authorize_invokes_service_with_incident_context(via_lambda):
    authz.set_audit_context("inc-7", "leash-disk-dev")
    d = authz.authorize("cleanDisk", "Instance", "i-p", "prod")
    assert d.allowed is False and d.policy_ids == ["ForbidProd"]
    assert d.audit_ref == {"pk": "inc-7", "sk": "2026-09-19T00:00:00.000001Z"}
    call = via_lambda.calls[0]
    assert call["FunctionName"] == "leash-authz" and call["InvocationType"] == "RequestResponse"
    payload = json.loads(call["Payload"])
    assert payload == {"op": "authorize", "action": "cleanDisk", "resource_type": "Instance", "resource_id": "i-p",
                       "resource_env": "prod", "context": None, "incident_id": "inc-7", "alarm_name": "leash-disk-dev"}


def test_scale_context_is_forwarded(via_lambda):
    authz.authorize("scaleGroup", "AutoScalingGroup", "g", "dev", {"desiredCapacity": 6})
    assert json.loads(via_lambda.calls[0]["Payload"])["context"] == {"desiredCapacity": 6}


def test_service_error_fails_closed(monkeypatch):
    fake = FakeLambda(reply={"errorMessage": "boom"}, function_error="Unhandled")
    monkeypatch.setenv("LEASH_AUTHZ_FUNCTION", "leash-authz")
    monkeypatch.setattr(authz, "_lambda_client", lambda: fake)
    d = authz.authorize("cleanDisk", "Instance", "i-1", "dev")
    assert d.allowed is False and d.reason.startswith("authz-error:") and d.audit_ref is None


def test_list_policies_via_service(via_lambda):
    via_lambda.reply = {"items": [{"id": "ForbidProd", "effect": "forbid", "description": "", "statement": "forbid (...)"}]}
    rows = authz.list_policies()
    assert rows[0]["id"] == "ForbidProd"
    assert json.loads(via_lambda.calls[0]["Payload"]) == {"op": "list_policies"}
