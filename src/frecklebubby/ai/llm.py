"""OpenAI-compatible chat client (plain httpx). Never log the API key or message contents."""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from ..models import Family
from ..services import ServiceError
from ..services.families import llm_config

log = logging.getLogger(__name__)

TRANSPORT: httpx.AsyncBaseTransport | None = None  # tests put a fake model server here
# CPU models are slow: allow long reads, but find a dead server fast.
TIMEOUT = httpx.Timeout(300.0, connect=5.0)
UNAVAILABLE = "The assistant is not available now."


class LlmError(ServiceError):
    status = 503

    def __init__(self, why: str = ""):
        super().__init__(UNAVAILABLE)
        self.why = why  # for logs and the settings test only


def _request(family: Family, messages: list[dict], schema: dict | None, max_tokens: int, stream: bool) -> dict:
    base_url, model, key = llm_config(family)
    body: dict[str, Any] = {"model": model or "default", "messages": messages, "temperature": 0,
                            "max_tokens": max_tokens, "stream": stream}
    if schema is not None:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "output", "strict": True,
                                                                          "schema": schema}}
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return {"url": f"{base_url.rstrip('/')}/chat/completions", "json": body, "headers": headers}


@asynccontextmanager
async def _client():
    async with httpx.AsyncClient(transport=TRANSPORT, timeout=TIMEOUT) as c:
        yield c


def _fail(err: Exception) -> LlmError:
    why = f"HTTP {err.response.status_code}" if isinstance(err, httpx.HTTPStatusError) else type(err).__name__
    log.warning("Model server call failed: %s", why)
    return LlmError(why)


async def complete(family: Family, messages: list[dict], schema: dict | None = None, max_tokens: int = 1024) -> str:
    """One answer. With a schema the server constrains the output to that JSON schema."""
    try:
        async with _client() as c:
            r = await c.post(**_request(family, messages, schema, max_tokens, False))
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"] or ""
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as err:
        raise _fail(err) from err


async def complete_json(family: Family, messages: list[dict], schema: dict, max_tokens: int = 1024) -> dict:
    out = await complete(family, messages, schema, max_tokens)
    try:
        return json.loads(out)
    except ValueError as err:
        raise _fail(err) from err


@asynccontextmanager
async def stream(family: Family, messages: list[dict], max_tokens: int = 700):
    """`async with stream(...) as tokens:` connects first (LlmError if the server is down), then yields text."""
    try:
        async with _client() as c, c.stream("POST", **_request(family, messages, None, max_tokens, True)) as r:
            r.raise_for_status()
            yield _tokens(r)
    except httpx.HTTPError as err:
        raise _fail(err) from err


async def _tokens(r: httpx.Response) -> AsyncIterator[str]:
    async for line in r.aiter_lines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        try:
            delta = json.loads(data)["choices"][0].get("delta", {})
        except (ValueError, KeyError, IndexError):
            continue
        if delta.get("content"):
            yield delta["content"]


async def test(family: Family) -> dict:
    """Settings "Test connection": one tiny request."""
    _, model, _ = llm_config(family)
    try:
        async with _client() as c:
            r = await c.post(**_request(family, [{"role": "user", "content": "Say OK."}], None, 5, False))
            r.raise_for_status()
            return {"ok": True, "detail": "The model server answered.", "model": r.json().get("model") or model}
    except (httpx.HTTPError, ValueError) as err:
        e = _fail(err)
        return {"ok": False, "detail": f"{UNAVAILABLE} ({e.why})", "model": model}
