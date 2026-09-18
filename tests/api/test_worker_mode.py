"""Worker mode (REQUEST_QUEUE_URL): /ask and /redteam are queued, /reply serves the answer."""

import json

import common.audit
from api import handler as h


class FakeSqs:
    def __init__(self):
        self.sent = []

    def send_message(self, QueueUrl, MessageBody):
        self.sent.append((QueueUrl, json.loads(MessageBody)))
        return {"MessageId": "m1"}


def _worker(monkeypatch):
    sqs = FakeSqs()
    monkeypatch.setenv("REQUEST_QUEUE_URL", "https://sqs/leash-requests")
    monkeypatch.delenv("AGENT_FUNCTION_NAME", raising=False)
    monkeypatch.delenv("REDTEAM_FUNCTION_NAME", raising=False)
    monkeypatch.setattr(h, "_sqs_client", lambda: sqs)
    return sqs


def test_ask_is_queued_and_returns_incident_id(monkeypatch):
    sqs = _worker(monkeypatch)
    resp = h.handler({"routeKey": "POST /ask", "body": json.dumps({"message": "terminate i-1"})}, None)
    assert resp["statusCode"] == 202
    body = json.loads(resp["body"])
    assert body["status"] == "queued" and body["incident_id"].startswith("chat-")
    url, msg = sqs.sent[0]
    assert url == "https://sqs/leash-requests"
    assert msg == {"kind": "chat", "incident_id": body["incident_id"], "message": "terminate i-1"}


def test_redteam_is_queued(monkeypatch):
    sqs = _worker(monkeypatch)
    resp = h.handler({"routeKey": "POST /redteam", "body": json.dumps({"n": 7, "arms": ["leashed"]})}, None)
    assert resp["statusCode"] == 202
    _, msg = sqs.sent[0]
    assert msg["kind"] == "redteam" and msg["n"] == 7 and msg["arms"] == ["leashed"] and msg["run_id"]


def test_reply_pending_then_ready(monkeypatch):
    store = {}
    monkeypatch.setattr(common.audit, "get_reply", lambda incident_id: store.get(incident_id))
    resp = h.handler({"routeKey": "GET /reply", "queryStringParameters": {"incident_id": "chat-1"}}, None)
    assert resp["statusCode"] == 202 and json.loads(resp["body"])["status"] == "pending"
    store["chat-1"] = {"reply": "DENIED by ForbidDestructive", "at": "t"}
    resp = h.handler({"routeKey": "GET /reply", "queryStringParameters": {"incident_id": "chat-1"}}, None)
    assert resp["statusCode"] == 200 and json.loads(resp["body"])["reply"] == "DENIED by ForbidDestructive"
    assert h.handler({"routeKey": "GET /reply"}, None)["statusCode"] == 400


def test_reply_rows_roundtrip_through_audit_module(monkeypatch):
    class Ddb:
        def __init__(self):
            self.items = {}

        def put_item(self, TableName, Item):
            self.items[(Item["pk"]["S"], Item["sk"]["S"])] = Item

        def get_item(self, TableName, Key):
            it = self.items.get((Key["pk"]["S"], Key["sk"]["S"]))
            return {"Item": it} if it else {}

    ddb = Ddb()
    monkeypatch.setenv("AUDIT_TABLE", "t")
    monkeypatch.setattr(common.audit, "_client", lambda: ddb)
    common.audit.write_reply("chat-9", "all good")
    assert common.audit.get_reply("chat-9")["reply"] == "all good"
    assert common.audit.get_reply("chat-8") is None
    assert ddb.items[("chat-9", "reply")]["gsi1pk"]["S"] == "REPLY"
