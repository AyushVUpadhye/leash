"""GET /policies relays common.authz.list_policies with CORS, and surfaces failures as 500."""

import json

import common.authz
from api import handler as h


def test_policies_route_relays_rows(monkeypatch):
    rows = [{"id": "ForbidProd", "effect": "forbid", "description": "", "statement": "forbid (...)"}]
    monkeypatch.setattr(common.authz, "list_policies", lambda: rows)
    resp = h.handler({"routeKey": "GET /policies"}, None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"items": rows}
    assert resp["headers"]["Access-Control-Allow-Origin"] == "*"


def test_policies_route_failure_is_500_with_message(monkeypatch):
    def boom():
        raise RuntimeError("avp down")

    monkeypatch.setattr(common.authz, "list_policies", boom)
    resp = h.handler({"routeKey": "GET /policies"}, None)
    assert resp["statusCode"] == 500
    assert "avp down" in json.loads(resp["body"])["error"]
