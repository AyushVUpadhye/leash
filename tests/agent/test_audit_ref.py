"""When the authorizer service already wrote the row, the tool fills in the result, no second row."""

import pytest

from agent import aws_helpers, tools


class FakeEc2:
    def describe_instances(self, InstanceIds):
        return {"Reservations": [{"Instances": [{"InstanceId": InstanceIds[0], "State": {"Name": "running"},
                                                 "Tags": [{"Key": "env", "Value": "dev"}]}]}]}


class FakeSsm:
    def send_command(self, **kwargs):
        return {"Command": {"CommandId": "cmd-1"}}

    def get_command_invocation(self, CommandId, InstanceId):
        return {"Status": "Success", "StandardOutputContent": "disk_used_percent before=93 after=41\n",
                "StandardErrorContent": ""}


@pytest.fixture
def clients(monkeypatch):
    box = {"ec2": FakeEc2(), "ssm": FakeSsm()}
    monkeypatch.setattr(aws_helpers, "client", lambda name: box[name])
    monkeypatch.setattr(tools.aws, "client", lambda name: box[name])
    return box


def test_allow_with_audit_ref_updates_instead_of_writing(clients, monkeypatch, decision_cls):
    updates, writes = [], []
    monkeypatch.setattr("common.authz.authorize",
                        lambda *a, **k: decision_cls(True, ["PermitDevRemediation"], "permit", [],
                                                     audit_ref={"pk": "inc-1", "sk": "t1"}))
    monkeypatch.setattr("common.audit.update_result", lambda ref, result: updates.append((ref, result)))
    monkeypatch.setattr("common.audit.write_audit", lambda **kw: writes.append(kw))
    out = tools.clean_disk("i-dev")
    assert out.startswith("ALLOWED by PermitDevRemediation")
    assert writes == [] and updates and updates[0][0] == {"pk": "inc-1", "sk": "t1"}
    assert "before=93 after=41" in updates[0][1]


def test_deny_with_audit_ref_updates_nothing_twice(clients, monkeypatch, decision_cls):
    updates, writes = [], []
    monkeypatch.setattr("common.authz.authorize",
                        lambda *a, **k: decision_cls(False, ["ForbidProd"], "forbid", [],
                                                     audit_ref={"pk": "inc-2", "sk": "t2"}))
    monkeypatch.setattr("common.audit.update_result", lambda ref, result: updates.append((ref, result)))
    monkeypatch.setattr("common.audit.write_audit", lambda **kw: writes.append(kw))
    out = tools.clean_disk("i-dev")
    assert "DENIED by ForbidProd" in out
    assert writes == [] and updates == [({"pk": "inc-2", "sk": "t2"}, "skipped (denied)")]


def test_set_context_reaches_authz_audit_context():
    from common import authz

    tools.set_context("inc-42", "leash-ecs-dev")
    assert authz._AUDIT_CTX == {"incident_id": "inc-42", "alarm_name": "leash-ecs-dev"}
