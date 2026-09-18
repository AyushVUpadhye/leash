"""The four Cedar policies, evaluated for real with cedarpy through common.authz.authorize."""

from pathlib import Path

import pytest

import common.authz as authz
from common.authz import Decision, authorize

ROOT = Path(__file__).resolve().parents[2]


def test_real_common_package_is_under_test():
    """Guard against the agent/api conftest stubs: this must be src/common/authz.py."""
    assert Path(authz.__file__).resolve() == ROOT / "src" / "common" / "authz.py"


def test_dev_clean_disk_allowed(local_authz):
    d = authorize("cleanDisk", "Instance", "i-dev", "dev")
    assert isinstance(d, Decision)
    assert d.allowed is True
    assert d.policy_ids == ["PermitDevRemediation"]
    assert d.errors == []


@pytest.mark.parametrize("action,rtype", [
    ("cleanDisk", "Instance"),
    ("restartService", "EcsService"),
    ("scaleGroup", "AutoScalingGroup"),
])
def test_prod_is_denied_by_forbid_prod(local_authz, action, rtype):
    ctx = {"desiredCapacity": 1} if action == "scaleGroup" else None
    d = authorize(action, rtype, "res-prod", "prod", ctx)
    assert d.allowed is False
    assert d.policy_ids == ["ForbidProd"]


def test_terminate_denied_by_forbid_destructive_even_on_dev(local_authz):
    d = authorize("terminateInstance", "Instance", "i-dev", "dev")
    assert d.allowed is False
    assert d.policy_ids == ["ForbidDestructive"]


@pytest.mark.parametrize("rtype", ["Instance", "EcsService", "AutoScalingGroup"])
def test_delete_denied_for_every_resource_type(local_authz, rtype):
    d = authorize("deleteResource", rtype, "r-1", "dev")
    assert d.allowed is False and "ForbidDestructive" in d.policy_ids


def test_scale_above_cap_denied(local_authz):
    d = authorize("scaleGroup", "AutoScalingGroup", "leash-dev-asg", "dev", {"desiredCapacity": 5})
    assert d.allowed is False
    assert d.policy_ids == ["ForbidScaleAboveCap"]


def test_scale_at_cap_allowed(local_authz):
    d = authorize("scaleGroup", "AutoScalingGroup", "leash-dev-asg", "dev", {"desiredCapacity": 4})
    assert d.allowed is True and d.policy_ids == ["PermitDevRemediation"]


def test_unknown_env_denied_by_default(local_authz):
    """No env tag -> env "unknown" -> no permit matches -> DENY with no determining policy."""
    d = authorize("restartService", "EcsService", "c/s", "unknown")
    assert d.allowed is False
    assert d.policy_ids == []
    assert "default" in d.reason


def test_scale_without_context_fails_closed(local_authz):
    """Schema says scaleGroup needs desiredCapacity: a missing context is an error, not an ALLOW."""
    d = authorize("scaleGroup", "AutoScalingGroup", "leash-dev-asg", "dev")
    assert d.allowed is False


def test_bad_resource_type_fails_closed(local_authz):
    d = authorize("cleanDisk", "Bucket", "b", "dev")
    assert d.allowed is False and d.reason.startswith("authz-error:")


def test_missing_cedar_dir_fails_closed(local_authz, monkeypatch, tmp_path):
    monkeypatch.setenv("LEASH_CEDAR_DIR", str(tmp_path / "nowhere"))
    d = authorize("cleanDisk", "Instance", "i-dev", "dev")
    assert d.allowed is False and d.reason.startswith("authz-error:")
