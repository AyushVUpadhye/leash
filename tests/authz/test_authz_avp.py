"""authorize() against a fake Verified Permissions client: request shape, id mapping, fail closed."""

import json

import pytest

import common.authz as authz


class FakeAvp:
    def __init__(self, decision="ALLOW", policy_ids=("SPabc",), errors=(), raise_exc=None):
        self.calls = []
        self.decision = decision
        self.policy_ids = list(policy_ids)
        self.errors = list(errors)
        self.raise_exc = raise_exc

    def is_authorized(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_exc:
            raise self.raise_exc
        return {
            "decision": self.decision,
            "determiningPolicies": [{"policyId": p} for p in self.policy_ids],
            "errors": [{"errorDescription": e} for e in self.errors],
        }


@pytest.fixture
def avp(monkeypatch):
    monkeypatch.delenv("LEASH_LOCAL_AUTHZ", raising=False)
    monkeypatch.setenv("POLICY_STORE_ID", "store-1")
    monkeypatch.setenv("POLICY_ID_MAP", json.dumps({"ForbidProd": "SPprod", "PermitDevRemediation": "SPabc"}))
    fake = FakeAvp()
    monkeypatch.setattr(authz, "_AVP", fake)
    return fake


def test_request_shape_and_typed_context(avp):
    d = authz.authorize("scaleGroup", "AutoScalingGroup", "leash-dev-asg", "dev", {"desiredCapacity": 3})
    assert d.allowed is True and d.policy_ids == ["PermitDevRemediation"]
    call = avp.calls[0]
    assert call["policyStoreId"] == "store-1"
    assert call["principal"] == {"entityType": "Leash::Agent", "entityId": "leash"}
    assert call["action"] == {"actionType": "Leash::Action", "actionId": "scaleGroup"}
    assert call["resource"] == {"entityType": "Leash::AutoScalingGroup", "entityId": "leash-dev-asg"}
    assert call["context"] == {"contextMap": {"desiredCapacity": {"long": 3}}}
    entity = [e for e in call["entities"]["entityList"] if e["identifier"]["entityType"] == "Leash::AutoScalingGroup"]
    assert entity[0]["attributes"] == {"env": {"string": "dev"}}


def test_deny_maps_opaque_policy_id_to_name(avp):
    avp.decision, avp.policy_ids = "DENY", ["SPprod", "SPunknown"]
    d = authz.authorize("cleanDisk", "Instance", "i-1", "prod")
    assert d.allowed is False
    assert d.policy_ids == ["ForbidProd", "SPunknown"]
    assert "ForbidProd" in d.reason


def test_avp_exception_fails_closed(avp):
    avp.raise_exc = RuntimeError("AccessDeniedException")
    d = authz.authorize("cleanDisk", "Instance", "i-1", "dev")
    assert d.allowed is False
    assert d.reason.startswith("authz-error:") and "AccessDeniedException" in d.reason
    assert d.errors == ["AccessDeniedException"]


def test_missing_policy_store_id_fails_closed(avp, monkeypatch):
    monkeypatch.delenv("POLICY_STORE_ID")
    d = authz.authorize("cleanDisk", "Instance", "i-1", "dev")
    assert d.allowed is False and "POLICY_STORE_ID" in d.reason


def test_avp_errors_are_surfaced(avp):
    avp.decision, avp.policy_ids, avp.errors = "DENY", [], ["entity missing attribute env"]
    d = authz.authorize("cleanDisk", "Instance", "i-1", "dev")
    assert d.allowed is False and d.errors == ["entity missing attribute env"]
