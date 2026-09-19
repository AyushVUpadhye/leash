"""A flapping alarm must not run the same runbook twice within the cooldown."""

from agent import handler, tools

ALARM = {
    "source": "aws.cloudwatch",
    "detail": {"alarmName": "leash-disk-dev", "state": {"value": "ALARM"},
               "configuration": {"metrics": [{"metricStat": {"metric": {"dimensions": {"InstanceId": "i-0abc"}}}}]}},
}


class Agent:
    system_prompt = ""

    def __init__(self):
        self.calls, self.messages = 0, []

    def __call__(self, prompt):
        self.calls += 1
        self.messages.append({"role": "assistant", "content": [{"toolUse": {"name": "clean_disk"}}]})
        return "cleaned"


def test_second_event_within_cooldown_is_skipped(monkeypatch):
    agent = Agent()
    monkeypatch.setattr(handler, "_AGENT", None)
    monkeypatch.setattr(handler, "build_agent", lambda incident_id: agent)
    monkeypatch.setattr(tools, "notify", lambda summary: "ok")
    handler._RECENT.clear()
    first = handler.handler(ALARM, None)
    second = handler.handler(ALARM, None)
    assert first["reply"] == "cleaned" and agent.calls == 1
    assert second["reply"].startswith("ignored: leash-disk-dev was handled")


def test_event_after_cooldown_runs_again(monkeypatch):
    agent = Agent()
    monkeypatch.setattr(handler, "_AGENT", None)
    monkeypatch.setattr(handler, "build_agent", lambda incident_id: agent)
    monkeypatch.setattr(tools, "notify", lambda summary: "ok")
    handler._RECENT.clear()
    handler._RECENT["leash-disk-dev"] = 0.0  # handled long ago
    handler.handler(ALARM, None)
    assert agent.calls == 1
    assert not handler._recently_handled("leash-ecs-dev", 10.0)
