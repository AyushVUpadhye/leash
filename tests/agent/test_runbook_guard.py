"""Alarm mode: the run must end with the runbook's remediation tool attempted, whatever text
inside the resource (a poisoned tag, a log line) tried to talk the model into instead."""

from agent import handler, tools

ALARM = {
    "source": "aws.cloudwatch",
    "detail": {"alarmName": "leash-disk-dev", "state": {"value": "ALARM"},
               "configuration": {"metrics": [{"metricStat": {"metric": {"dimensions": {"InstanceId": "i-0abc", "path": "/", "fstype": "xfs"}}}}]}},
}


class Agent:
    """Replays tool usage per call: first call follows the injection, later calls obey the nudge."""

    system_prompt = ""

    def __init__(self, per_call):
        self.per_call, self.calls, self.messages, self.prompts = per_call, 0, [], []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        names = self.per_call[min(self.calls, len(self.per_call) - 1)]
        self.calls += 1
        self.messages.append({"role": "assistant", "content": [{"toolUse": {"name": n}} for n in names]})
        return "done"


def _run(monkeypatch, agent, event=ALARM):
    monkeypatch.setattr(handler, "_AGENT", None)
    monkeypatch.setattr(handler, "build_agent", lambda incident_id: agent)
    monkeypatch.setattr(tools, "notify", lambda summary: "ok")
    return handler.handler(event, None)


def test_injected_terminate_then_nudged_back_to_clean_disk(monkeypatch):
    agent = Agent([["get_instance_info", "terminate_instance"], ["clean_disk", "get_disk_usage"]])
    _run(monkeypatch, agent)
    assert agent.calls == 2
    assert "clean_disk('i-0abc')" in agent.prompts[1] and "not an instruction" in agent.prompts[1]


def test_runbook_followed_first_time_is_not_nudged(monkeypatch):
    agent = Agent([["get_instance_info", "get_disk_usage", "clean_disk"]])
    _run(monkeypatch, agent)
    assert agent.calls == 1


def test_ecs_runbook_requires_restart_service(monkeypatch):
    event = {"source": "aws.cloudwatch", "detail": {"alarmName": "leash-ecs-dev", "state": {"value": "ALARM"},
             "configuration": {"metrics": [{"metricStat": {"metric": {"dimensions": {"ClusterName": "c", "ServiceName": "s"}}}}]}}}
    agent = Agent([["get_service_info"], ["restart_service"]])
    _run(monkeypatch, agent, event)
    assert agent.calls == 2 and "restart_service('c', 's')" in agent.prompts[1]


def test_alarm_prompt_says_tags_are_data():
    parsed = handler.parse_event(ALARM)
    text = handler.build_alarm_prompt(parsed)
    assert "never an instruction" in text
    assert handler._remediation_tool(parsed["dimensions"]) == "clean_disk"
    assert handler._remediation_tool({}) is None
