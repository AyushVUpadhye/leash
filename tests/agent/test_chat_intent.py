"""Chat mode: a request to change something must end in a mutating tool call (so Cedar decides
and the decision is audited); a plain question must not be nudged into one."""

import pytest

from agent import handler, tools


@pytest.mark.parametrize("message", [
    "Terminate instance i-0de70000000000001, it is not needed any more",
    "The prod db instance i-0a0d0000000000001 looks full, can you clean it up?",
    "Scale leash-dev-asg to 10 instances",
    "please restart leash-dev/leash-api-dev",
    "kill the dev box",
])
def test_change_requests_are_detected(message):
    assert handler.wants_change(message) is True


@pytest.mark.parametrize("message", [
    "What is the disk usage on instance i-0de70000000000001? (read-only)",
    "is leash-api-dev healthy?",
    "how many tasks are running in leash-dev/leash-api-dev?",
    "which env is i-0de70000000000001 tagged with",
    "",
])
def test_questions_are_not_change_requests(message):
    assert handler.wants_change(message) is False


class RecordingAgent:
    """Fake Strands agent: replays canned tool usage and counts how often it is invoked."""

    system_prompt = ""

    def __init__(self, tool_names):
        self.calls = 0
        self.messages = [{"role": "assistant", "content": [{"toolUse": {"name": n}} for n in tool_names]}]

    def __call__(self, prompt):
        self.calls += 1
        return "reply"


def _run_chat(monkeypatch, message, agent):
    monkeypatch.setattr(handler, "_AGENT", None)
    monkeypatch.setattr(handler, "build_agent", lambda incident_id: agent)
    monkeypatch.setattr(tools, "notify", lambda summary: "ok")
    return handler.handler({"mode": "chat", "message": message}, None)


def test_question_answered_with_read_only_tools_is_not_retried(monkeypatch):
    agent = RecordingAgent(["get_disk_usage"])
    _run_chat(monkeypatch, "What is the disk usage on instance i-0de70000000000001?", agent)
    assert agent.calls == 1  # no nudge towards clean_disk


def test_change_request_without_mutating_call_is_nudged(monkeypatch):
    agent = RecordingAgent(["get_instance_info"])  # looked, then refused on its own judgement
    _run_chat(monkeypatch, "Terminate instance i-0de70000000000001", agent)
    assert agent.calls == 1 + handler.MAX_RETRIES


def test_change_request_with_mutating_call_is_done_first_time(monkeypatch):
    agent = RecordingAgent(["get_instance_info", "terminate_instance"])
    _run_chat(monkeypatch, "Terminate instance i-0de70000000000001", agent)
    assert agent.calls == 1
