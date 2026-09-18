"""common.authz.list_policies: the leash, readable, from both backends."""

from pathlib import Path

import common.authz as authz

ROOT = Path(__file__).resolve().parents[2]
POLICY_NAMES = list(authz.POLICY_NAMES)


def test_local_lists_the_four_files_in_order(local_authz):
    rows = authz.list_policies()
    assert [r["id"] for r in rows] == POLICY_NAMES
    for row in rows:
        on_disk = (ROOT / "cedar" / "policies" / f"{row['id']}.cedar").read_text(encoding="utf-8")
        assert row["statement"] == on_disk.strip()
        assert row["effect"] == ("permit" if row["id"].startswith("Permit") else "forbid")


class FakeAvp:
    """ListPolicies gives ids + descriptions; GetPolicy gives the statement text."""

    def __init__(self):
        self.calls = []

    def list_policies(self, policyStoreId):
        self.calls.append(("list", policyStoreId))
        return {"policies": [
            {"policyId": "SPfp", "definition": {"static": {"description": "no prod"}}},
            {"policyId": "SPpd", "definition": {"static": {"description": "dev ok"}}},
        ]}

    def get_policy(self, policyStoreId, policyId):
        self.calls.append(("get", policyId))
        text = {"SPfp": 'forbid (principal, action, resource) when { resource.env == "prod" };',
                "SPpd": "permit (principal, action, resource);"}[policyId]
        desc = {"SPfp": "no prod", "SPpd": "dev ok"}[policyId]
        return {"definition": {"static": {"statement": text, "description": desc}}}


def test_avp_maps_opaque_ids_to_names_and_keeps_canonical_order(monkeypatch):
    fake = FakeAvp()
    monkeypatch.delenv("LEASH_LOCAL_AUTHZ", raising=False)
    monkeypatch.setenv("POLICY_STORE_ID", "store-1")
    monkeypatch.setenv("POLICY_ID_MAP", '{"ForbidProd": "SPfp", "PermitDevRemediation": "SPpd"}')
    monkeypatch.setattr(authz, "_avp_client", lambda: fake)
    rows = authz.list_policies()
    assert [r["id"] for r in rows] == ["PermitDevRemediation", "ForbidProd"]
    assert rows[1] == {"id": "ForbidProd", "effect": "forbid", "description": "no prod",
                       "statement": 'forbid (principal, action, resource) when { resource.env == "prod" };'}
    assert ("list", "store-1") in fake.calls and ("get", "SPfp") in fake.calls
