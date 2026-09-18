"""write_audit / list_audit against a fake DynamoDB client: item keys, types, query shape."""

import re

import pytest

import common.audit as audit
from common.authz import Decision


class FakeDdb:
    def __init__(self):
        self.items = []
        self.queries = []

    def put_item(self, TableName, Item):
        self.items.append((TableName, Item))
        return {}

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return {"Items": [
            {"pk": {"S": "inc-2"}, "sk": {"S": "2026-09-18T03:12:08.000001Z"}, "decision": {"S": "DENY"},
             "policy_ids": {"L": [{"S": "ForbidProd"}]}},
            {"pk": {"S": "inc-1"}, "sk": {"S": "2026-09-18T03:12:07.000001Z"}, "decision": {"S": "ALLOW"},
             "policy_ids": {"L": []}},
        ]}


@pytest.fixture
def ddb(monkeypatch):
    fake = FakeDdb()
    monkeypatch.setattr(audit, "_DDB", fake)
    monkeypatch.setenv("AUDIT_TABLE", "leash-audit")
    return fake


def test_write_audit_item_shape(ddb):
    decision = Decision(allowed=False, policy_ids=["ForbidProd"], reason="forbid by ForbidProd", errors=[])
    item = audit.write_audit("inc-1", "cleanDisk", "Instance", "i-1", "prod", decision, "skipped (denied)",
                             alarm_name="leash-disk-dev", summary="s")
    table, typed = ddb.items[0]
    assert table == "leash-audit"
    assert typed["pk"] == {"S": "inc-1"}
    assert typed["gsi1pk"] == {"S": "ALL"}
    assert typed["decision"] == {"S": "DENY"}
    assert typed["policy_ids"] == {"L": [{"S": "ForbidProd"}]}
    assert typed["reason"] == {"S": "forbid by ForbidProd"}
    assert typed["result"] == {"S": "skipped (denied)"}
    assert typed["alarm_name"] == {"S": "leash-disk-dev"} and typed["summary"] == {"S": "s"}
    assert typed["resource_type"] == {"S": "Instance"} and typed["resource_env"] == {"S": "prod"}
    # sk: ISO8601 UTC with microseconds
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", typed["sk"]["S"])
    assert item["sk"] == typed["sk"]["S"] and item["decision"] == "DENY"


def test_write_audit_allow(ddb):
    decision = Decision(allowed=True, policy_ids=["PermitDevRemediation"], reason="permit", errors=[])
    item = audit.write_audit("inc-1", "cleanDisk", "Instance", "i-1", "dev", decision, "ssm Success")
    assert item["decision"] == "ALLOW" and item["alarm_name"] == "" and item["summary"] == ""


def test_list_audit_queries_gsi_newest_first(ddb):
    rows = audit.list_audit(limit=2)
    q = ddb.queries[0]
    assert q["IndexName"] == "gsi1" and q["ScanIndexForward"] is False and q["Limit"] == 2
    assert q["ExpressionAttributeValues"] == {":all": {"S": "ALL"}}
    assert rows[0] == {"pk": "inc-2", "sk": "2026-09-18T03:12:08.000001Z", "decision": "DENY", "policy_ids": ["ForbidProd"]}
    assert rows[1]["policy_ids"] == []


def test_missing_table_env_raises(ddb, monkeypatch):
    monkeypatch.delenv("AUDIT_TABLE")
    with pytest.raises(KeyError):
        audit.list_audit()
