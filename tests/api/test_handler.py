"""Unit tests for src/api/handler.py. No AWS calls: list_audit and the Lambda client are faked."""

import base64
import io
import json

import pytest

import common.audit
from api import handler as h


class FakeLambda:
    """Records invoke() calls and returns a canned agent payload."""

    def __init__(self, payload=None, function_error=None):
        self.calls = []
        self.payload = payload if payload is not None else {"reply": "hi", "incident_id": "inc-1"}
        self.function_error = function_error

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        resp = {"StatusCode": 200, "Payload": io.BytesIO(json.dumps(self.payload).encode())}
        if self.function_error:
            resp["FunctionError"] = self.function_error
        return resp


@pytest.fixture
def fake_lambda(monkeypatch):
    fake = FakeLambda()
    monkeypatch.setattr(h, "_lambda_client", lambda: fake)
    monkeypatch.setenv("AGENT_FUNCTION_NAME", "leash-AgentFunction")
    return fake


@pytest.fixture
def audit_rows(monkeypatch):
    rows = [{"pk": "inc-1", "sk": "2026-09-18T00:00:00.000001", "decision": "DENY", "policy_ids": ["ForbidProd"]}]
    seen = {}

    def fake_list(limit=50):
        seen["limit"] = limit
        return rows[:limit]

    monkeypatch.setattr(common.audit, "list_audit", fake_list)
    return rows, seen


def event(route, body=None, qs=None, b64=False):
    e = {"routeKey": route, "queryStringParameters": qs}
    if body is not None:
        raw = json.dumps(body)
        e["body"] = base64.b64encode(raw.encode()).decode() if b64 else raw
        e["isBase64Encoded"] = b64
    return e


def body_of(resp):
    return json.loads(resp["body"])


def test_health():
    resp = h.handler(event("GET /health"), None)
    assert resp["statusCode"] == 200
    assert body_of(resp)["ok"] is True and "brain" in body_of(resp)


def test_cors_headers_on_every_response(fake_lambda, audit_rows):
    for ev in (event("GET /health"), event("GET /audit"), event("POST /ask", {"message": "x"}), event("GET /nope")):
        resp = h.handler(ev, None)
        assert resp["headers"]["Access-Control-Allow-Origin"] == "*"
        assert resp["headers"]["Content-Type"] == "application/json"


def test_audit_default_limit(audit_rows):
    rows, seen = audit_rows
    resp = h.handler(event("GET /audit"), None)
    assert resp["statusCode"] == 200
    assert body_of(resp)["items"] == rows
    assert seen["limit"] == 50


def test_audit_limit_param_and_clamp(audit_rows):
    _, seen = audit_rows
    h.handler(event("GET /audit", qs={"limit": "5"}), None)
    assert seen["limit"] == 5
    h.handler(event("GET /audit", qs={"limit": "9999"}), None)
    assert seen["limit"] == h.MAX_AUDIT_LIMIT
    resp = h.handler(event("GET /audit", qs={"limit": "abc"}), None)
    assert resp["statusCode"] == 400
    assert "error" in body_of(resp)


def test_ask_invokes_agent_and_relays_reply(fake_lambda):
    resp = h.handler(event("POST /ask", {"message": "please terminate i-123"}), None)
    assert resp["statusCode"] == 200
    assert body_of(resp) == {"reply": "hi", "incident_id": "inc-1"}
    call = fake_lambda.calls[0]
    assert call["FunctionName"] == "leash-AgentFunction"
    assert call["InvocationType"] == "RequestResponse"
    assert json.loads(call["Payload"]) == {"mode": "chat", "message": "please terminate i-123"}


def test_ask_decodes_base64_body(fake_lambda):
    resp = h.handler(event("POST /ask", {"message": "scale to 10"}, b64=True), None)
    assert resp["statusCode"] == 200
    assert json.loads(fake_lambda.calls[0]["Payload"])["message"] == "scale to 10"


def test_ask_rejects_bad_input(fake_lambda):
    assert h.handler(event("POST /ask", {}), None)["statusCode"] == 400
    assert h.handler(event("POST /ask", {"message": "   "}), None)["statusCode"] == 400
    bad = {"routeKey": "POST /ask", "body": "{not json", "isBase64Encoded": False}
    resp = h.handler(bad, None)
    assert resp["statusCode"] == 400
    assert "error" in body_of(resp)
    assert fake_lambda.calls == []


def test_ask_agent_function_error_becomes_502(monkeypatch):
    fake = FakeLambda(payload={"errorMessage": "boom"}, function_error="Unhandled")
    monkeypatch.setattr(h, "_lambda_client", lambda: fake)
    monkeypatch.setenv("AGENT_FUNCTION_NAME", "leash-AgentFunction")
    resp = h.handler(event("POST /ask", {"message": "hi"}), None)
    assert resp["statusCode"] == 502
    assert "boom" in body_of(resp)["error"]


def test_ask_without_function_name_is_500(monkeypatch):
    monkeypatch.delenv("AGENT_FUNCTION_NAME", raising=False)
    resp = h.handler(event("POST /ask", {"message": "hi"}), None)
    assert resp["statusCode"] == 500


def test_unknown_route_404():
    resp = h.handler(event("GET /does-not-exist"), None)
    assert resp["statusCode"] == 404
    assert "unknown route" in body_of(resp)["error"]


def test_options_preflight_is_204():
    resp = h.handler({"routeKey": "OPTIONS /ask"}, None)
    assert resp["statusCode"] == 204
    assert resp["headers"]["Access-Control-Allow-Origin"] == "*"


def test_exception_inside_route_is_500_with_cors(monkeypatch):
    def boom(limit=50):
        raise RuntimeError("dynamo down")

    monkeypatch.setattr(common.audit, "list_audit", boom)
    resp = h.handler(event("GET /audit"), None)
    assert resp["statusCode"] == 500
    assert "dynamo down" in body_of(resp)["error"]
    assert resp["headers"]["Access-Control-Allow-Origin"] == "*"
