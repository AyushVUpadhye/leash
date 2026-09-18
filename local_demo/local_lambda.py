"""Fakes the one boto3 call src/api/handler.py makes to reach the agent: lambda.invoke(...).
Locally there is no Lambda service, so `invoke` just calls agent.handler.handler() in-process
and wraps the result exactly like the real Payload StreamingBody (a .read()-able object).
"""

import io
import json


class _FakePayload:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data


class _FakeLambdaClient:
    def invoke(self, FunctionName, InvocationType, Payload):
        from agent.handler import handler as agent_handler

        event = json.loads(Payload)
        try:
            result = agent_handler(event, None)
        except Exception as exc:  # mirror a real Lambda's FunctionError shape
            body = json.dumps({"errorMessage": str(exc)}).encode("utf-8")
            return {"FunctionError": "Unhandled", "Payload": _FakePayload(body)}
        return {"Payload": _FakePayload(json.dumps(result, default=str).encode("utf-8"))}


def install():
    import api.handler as api_handler

    api_handler._lambda_client = lambda: _FakeLambdaClient()
