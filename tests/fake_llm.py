"""A scripted OpenAI-compatible model server on httpx.MockTransport."""

import json

import httpx
import pytest

from frecklebubby.ai import llm


class FakeLLM:
    def __init__(self):
        self.replies: list[str | dict] = []  # dict = JSON output for response_format calls
        self.requests: list[dict] = []
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("refused", request=request)
        body = json.loads(request.content)
        self.requests.append(body)
        reply = self.replies.pop(0) if self.replies else "OK"
        text = json.dumps(reply) if isinstance(reply, dict) else reply
        if body.get("stream"):
            parts = [text[i:i + 4] for i in range(0, len(text), 4)]  # small tokens split [n] marks
            lines = [f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}\n\n" for p in parts]
            return httpx.Response(200, content="".join(lines) + "data: [DONE]\n\n",
                                  headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"model": "fake-model", "choices": [{"message": {"content": text}}]})


@pytest.fixture(name="fake_llm")
def fake_llm_fixture(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(llm, "TRANSPORT", httpx.MockTransport(fake.handler))
    return fake


def sse_events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out
