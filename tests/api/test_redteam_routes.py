"""GET/POST /redteam on the API Lambda."""

import io
import json

import common.audit
from api import handler as h


class FakeLambda:
    def __init__(self):
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        return {"StatusCode": 202, "Payload": io.BytesIO(b"")}


def test_get_redteam_returns_rows_and_summary(monkeypatch):
    rows = [{"pk": "redteam-r1", "run_id": "r1", "tactic": "direct", "persuaded": "true",
             "leashed_executed": "false", "unleashed_executed": "true", "leashed_denials": ["ForbidDestructive"]}]
    monkeypatch.setattr(common.audit, "list_redteam", lambda limit=200: rows)
    resp = h.handler({"routeKey": "GET /redteam"}, None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200 and body["items"] == rows
    assert body["summary"]["attacks"] == 1 and body["summary"]["unleashed_executed"] == 1
    assert body["summary"]["leashed_executed"] == 0


def test_post_redteam_invokes_async_and_clamps(monkeypatch):
    fake = FakeLambda()
    monkeypatch.setattr(h, "_lambda_client", lambda: fake)
    monkeypatch.setenv("REDTEAM_FUNCTION_NAME", "leash-redteam")
    resp = h.handler({"routeKey": "POST /redteam", "body": json.dumps({"n": 5000, "arms": ["leashed"]})}, None)
    assert resp["statusCode"] == 202
    body = json.loads(resp["body"])
    assert body["n"] == h.MAX_REDTEAM_N and body["arms"] == ["leashed"] and body["run_id"]
    call = fake.calls[0]
    assert call["FunctionName"] == "leash-redteam" and call["InvocationType"] == "Event"
    payload = json.loads(call["Payload"])
    assert payload["n"] == h.MAX_REDTEAM_N and payload["run_id"] == body["run_id"]


def test_post_redteam_rejects_bad_arms(monkeypatch):
    monkeypatch.setattr(h, "_lambda_client", lambda: FakeLambda())
    monkeypatch.setenv("REDTEAM_FUNCTION_NAME", "leash-redteam")
    resp = h.handler({"routeKey": "POST /redteam", "body": json.dumps({"arms": ["nuke"]})}, None)
    assert resp["statusCode"] == 400


def test_post_redteam_without_function_is_500(monkeypatch):
    monkeypatch.delenv("REDTEAM_FUNCTION_NAME", raising=False)
    resp = h.handler({"routeKey": "POST /redteam", "body": "{}"}, None)
    assert resp["statusCode"] == 500
