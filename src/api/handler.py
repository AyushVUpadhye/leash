"""Leash API Lambda.

Serves three HTTP API (payload format v2) routes behind API Gateway:

    GET  /health        -> {"ok": true}
    GET  /audit?limit=N -> {"items": [...]}   (newest first, via common.audit.list_audit)
    GET  /policies      -> {"items": [...]}   (the Cedar policies, via common.authz.list_policies)
    GET  /redteam       -> {"items": [...], "summary": {...}}  (attack rows + the numbers)
    POST /redteam       -> {"run_id": ...}   starts an attack run on the red-team Lambda (async)
    POST /ask           -> invokes the agent Lambda synchronously with
                           {"mode": "chat", "message": ...} and returns its JSON reply.

Every response carries permissive CORS headers so the static dashboard on S3 can call it.
Routing uses event["routeKey"] ("GET /audit"), which is how HTTP API v2 events identify the
matched route. See https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-integrations-lambda.html
"""

import base64
import json
import os

import boto3

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Content-Type": "application/json",
}

MAX_MESSAGE_CHARS = 2000
MAX_AUDIT_LIMIT = 200

_lambda = None


def _lambda_client():
    """Return a cached boto3 Lambda client (created lazily so tests can swap it out)."""
    global _lambda
    if _lambda is None:
        _lambda = boto3.client("lambda")
    return _lambda


def _response(status: int, body) -> dict:
    """Build an HTTP API v2 response with CORS headers and a JSON body."""
    return {"statusCode": status, "headers": dict(CORS_HEADERS), "body": json.dumps(body, default=str)}


def _error(status: int, message: str) -> dict:
    return _response(status, {"error": message})


def _read_body(event: dict):
    """Decode the request body (base64 if flagged) and parse it as a JSON object."""
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("body must be a JSON object")
    return data


def _health(event: dict) -> dict:
    return _response(200, {"ok": True})


def _audit(event: dict) -> dict:
    """List recent audit rows. Imported lazily so tests can monkeypatch common.audit."""
    from common.audit import list_audit

    params = event.get("queryStringParameters") or {}
    try:
        limit = int(params.get("limit", 50))
    except (TypeError, ValueError):
        return _error(400, "limit must be an integer")
    limit = max(1, min(limit, MAX_AUDIT_LIMIT))
    return _response(200, {"items": list_audit(limit=limit)})


def _policies(event: dict) -> dict:
    """The leash itself: every Cedar policy with its text, read from the same backend that
    enforces it (Verified Permissions in the cloud, the .cedar files in the local demo)."""
    from common.authz import list_policies

    return _response(200, {"items": list_policies()})


def _redteam_get(event: dict) -> dict:
    """Attack rows newest first plus the computed headline numbers."""
    from common.audit import list_redteam
    from redteam.runner import summarise

    params = event.get("queryStringParameters") or {}
    try:
        limit = int(params.get("limit", 200))
    except (TypeError, ValueError):
        return _error(400, "limit must be an integer")
    rows = list_redteam(limit=max(1, min(limit, 500)))
    return _response(200, {"items": rows, "summary": summarise(rows)})


MAX_REDTEAM_N = 100


def _redteam_post(event: dict) -> dict:
    """Kick off a run: n attacks, both arms by default. Returns immediately; rows stream in."""
    try:
        body = _read_body(event)
    except (ValueError, UnicodeDecodeError) as exc:
        return _error(400, f"invalid JSON body: {exc}")
    try:
        n = int(body.get("n", 20))
    except (TypeError, ValueError):
        return _error(400, "'n' must be an integer")
    n = max(1, min(n, MAX_REDTEAM_N))
    arms = body.get("arms") or ["leashed", "unleashed"]
    if not isinstance(arms, list) or not set(arms) <= {"leashed", "unleashed"}:
        return _error(400, "'arms' must be a list of 'leashed' and/or 'unleashed'")
    function_name = os.environ.get("REDTEAM_FUNCTION_NAME")
    if not function_name:
        return _error(500, "REDTEAM_FUNCTION_NAME is not configured")
    from redteam.runner import _now_id

    run_id = _now_id()
    payload = {"n": n, "arms": arms, "run_id": run_id, "use_model": bool(body.get("use_model", True))}
    _lambda_client().invoke(FunctionName=function_name, InvocationType="Event",
                            Payload=json.dumps(payload).encode("utf-8"))
    return _response(202, {"run_id": run_id, "n": n, "arms": arms})


def _ask(event: dict) -> dict:
    """Forward a human question to the agent Lambda and relay its reply."""
    try:
        body = _read_body(event)
    except (ValueError, UnicodeDecodeError) as exc:
        return _error(400, f"invalid JSON body: {exc}")

    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        return _error(400, "'message' (non-empty string) is required")
    if len(message) > MAX_MESSAGE_CHARS:
        return _error(400, f"message longer than {MAX_MESSAGE_CHARS} characters")

    function_name = os.environ.get("AGENT_FUNCTION_NAME")
    if not function_name:
        return _error(500, "AGENT_FUNCTION_NAME is not configured")

    payload = json.dumps({"mode": "chat", "message": message.strip()})
    # Synchronous invoke: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/lambda/client/invoke.html
    resp = _lambda_client().invoke(
        FunctionName=function_name, InvocationType="RequestResponse", Payload=payload.encode("utf-8")
    )
    raw = resp["Payload"].read()
    try:
        result = json.loads(raw or b"{}")
    except ValueError:
        return _error(502, "agent returned a non-JSON payload")
    if resp.get("FunctionError"):
        detail = result.get("errorMessage") if isinstance(result, dict) else str(result)
        return _error(502, f"agent failed: {detail}")
    if not isinstance(result, dict):
        result = {"reply": str(result)}
    return _response(200, result)


ROUTES = {
    "GET /health": _health,
    "GET /audit": _audit,
    "GET /policies": _policies,
    "GET /redteam": _redteam_get,
    "POST /redteam": _redteam_post,
    "POST /ask": _ask,
}


def handler(event, context):
    """Lambda entry point. Routes by HTTP API v2 routeKey; never raises to the caller."""
    route = event.get("routeKey")
    if not route:  # tolerate a hand-built event without routeKey
        http = (event.get("requestContext") or {}).get("http") or {}
        route = f"{http.get('method', '')} {event.get('rawPath', '')}".strip()
    if route.startswith("OPTIONS"):
        return _response(204, {})
    fn = ROUTES.get(route)
    if fn is None:
        return _error(404, f"unknown route: {route}")
    try:
        return fn(event)
    except Exception as exc:  # noqa: BLE001 - surface any failure as JSON, keep CORS headers
        return _error(500, f"{type(exc).__name__}: {exc}")
