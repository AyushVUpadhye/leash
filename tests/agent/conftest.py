"""Test setup for the agent Lambda.

Puts src/ on sys.path and sets LEASH_LOCAL_AUTHZ=1. The real src/common package is imported;
only when LEASH_STUB_COMMON=1 is set explicitly does a minimal stub (with the contract's Decision
dataclass) replace it, and then a loud warning is emitted so a green run cannot hide it.
"""

import os
import sys
import types
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("LEASH_LOCAL_AUTHZ", "1")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AUDIT_TABLE", "leash-audit-test")

if os.environ.get("LEASH_STUB_COMMON") != "1":
    import common.authz  # noqa: F401  (real Lane B package; ImportError here is a real failure)
    import common.audit  # noqa: F401
else:  # pragma: no cover - explicit opt-in only
    warnings.warn("LEASH_STUB_COMMON=1: src/common is STUBBED, Cedar/AVP/DynamoDB code is not under test")

    @dataclass
    class Decision:
        allowed: bool
        policy_ids: list = field(default_factory=list)
        reason: str = ""
        errors: list = field(default_factory=list)

    def _authorize(*args, **kwargs):
        raise RuntimeError("stub authorize called without monkeypatch")

    def _write_audit(*args, **kwargs):
        raise RuntimeError("stub write_audit called without monkeypatch")

    common = types.ModuleType("common")
    authz = types.ModuleType("common.authz")
    audit = types.ModuleType("common.audit")
    authz.Decision = Decision
    authz.authorize = _authorize
    audit.write_audit = _write_audit
    audit.list_audit = lambda limit=50: []
    common.authz = authz
    common.audit = audit
    sys.modules["common"] = common
    sys.modules["common.authz"] = authz
    sys.modules["common.audit"] = audit


@pytest.fixture
def decision_cls():
    from common.authz import Decision

    return Decision


@pytest.fixture
def audit_rows(monkeypatch):
    """Capture write_audit calls as a list of kwargs dicts."""
    rows: list = []

    def fake_write_audit(**kwargs):
        rows.append(kwargs)
        return kwargs

    monkeypatch.setattr("common.audit.write_audit", fake_write_audit)
    return rows


@pytest.fixture
def allow(monkeypatch, decision_cls):
    """Monkeypatch authorize to ALLOW everything; returns the list of calls."""
    calls: list = []

    def fake_authorize(action, resource_type, resource_id, resource_env, context=None):
        calls.append({"action": action, "resource_type": resource_type, "resource_id": resource_id,
                      "resource_env": resource_env, "context": context})
        return decision_cls(allowed=True, policy_ids=["PermitDevRemediation"], reason="permit", errors=[])

    monkeypatch.setattr("common.authz.authorize", fake_authorize)
    return calls


@pytest.fixture
def deny_prod(monkeypatch, decision_cls):
    """Monkeypatch authorize to DENY when env == prod (ForbidProd), else ALLOW."""
    calls: list = []

    def fake_authorize(action, resource_type, resource_id, resource_env, context=None):
        calls.append({"action": action, "resource_env": resource_env, "context": context})
        if resource_env == "prod":
            return decision_cls(allowed=False, policy_ids=["ForbidProd"], reason="forbid matched", errors=[])
        return decision_cls(allowed=True, policy_ids=["PermitDevRemediation"], reason="permit", errors=[])

    monkeypatch.setattr("common.authz.authorize", fake_authorize)
    return calls


@pytest.fixture(autouse=True)
def _no_incident_cooldown_between_tests():
    """The duplicate-incident guard remembers alarms per process; tests must not share it."""
    from agent import handler

    handler._RECENT.clear()
    yield
    handler._RECENT.clear()
