"""Gemini REST adapter with Ollama-compatible generation responses."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from urllib.parse import quote

import httpx
from fastapi.responses import JSONResponse, StreamingResponse

_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def is_gemini_model(model: object) -> bool:
    return isinstance(model, str) and model.startswith("gemini-")


def _extract_text(payload: dict) -> str:
    if not isinstance(payload, dict):
        raise ValueError("Gemini response must be an object")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        raise ValueError("Gemini response did not include a candidate")
    content = candidates[0].get("content")
    if not isinstance(content, dict):
        raise ValueError("Gemini candidate did not include content")
    parts = content.get("parts")
    if not isinstance(parts, list):
        raise ValueError("Gemini content did not include parts")
    return "".join(
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text", ""), str)
    )


def _ollama_chunk(model: str, text: str, done: bool) -> bytes:
    payload = {"model": model, "response": text, "done": done}
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


async def _stream_response(upstream: httpx.Response, model: str) -> AsyncIterator[bytes]:
    yielded_text = False
    try:
        async for line in upstream.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                payload = json.loads(data)
                text = _extract_text(payload)
            except (ValueError, json.JSONDecodeError):
                continue
            if text:
                yielded_text = True
                yield _ollama_chunk(model, text, False)
        if yielded_text:
            yield _ollama_chunk(model, "", True)
        else:
            yield json.dumps(
                {"error": {"detail": "Gemini returned no generated text"}, "done": True},
                ensure_ascii=False,
            ).encode("utf-8") + b"\n"
    except (httpx.HTTPError, json.JSONDecodeError):
        yield json.dumps(
            {"error": {"detail": "Gemini stream interrupted"}, "done": True},
            ensure_ascii=False,
        ).encode("utf-8") + b"\n"
    finally:
        await upstream.aclose()


async def generate_gemini(
    client: httpx.AsyncClient,
    api_key: str,
    model: str,
    prompt: str,
    *,
    system: str | None = None,
    stream: bool = False,
    timeout_seconds: float = 120.0,
) -> JSONResponse | StreamingResponse:
    if not api_key:
        return JSONResponse(
            {"detail": "GEMINI_API_KEY must be configured to use Gemini"},
            status_code=503,
        )

    contents = [{"role": "user", "parts": [{"text": prompt}]}]
    request_body: dict = {"contents": contents}
    if system:
        request_body["systemInstruction"] = {"parts": [{"text": system}]}

    action = "streamGenerateContent?alt=sse" if stream else "generateContent"
    url = f"{_GEMINI_API_BASE}/{quote(model, safe='')}:" + action
    request = client.build_request(
        "POST",
        url,
        headers={"x-goog-api-key": api_key, "content-type": "application/json"},
        json=request_body,
        timeout=httpx.Timeout(timeout_seconds),
    )

    try:
        upstream = await client.send(request, stream=stream)
    except httpx.TimeoutException:
        return JSONResponse({"detail": "Gemini request timed out"}, status_code=504)
    except httpx.RequestError:
        return JSONResponse({"detail": "Gemini service unavailable"}, status_code=502)

    if not upstream.is_success:
        await upstream.aclose()
        return JSONResponse(
            {"detail": f"Gemini request failed (HTTP {upstream.status_code})"},
            status_code=502,
        )

    if stream:
        return StreamingResponse(
            _stream_response(upstream, model),
            status_code=200,
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        payload = upstream.json()
        text = _extract_text(payload)
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"detail": "Gemini returned an invalid response"}, status_code=502)
    finally:
        await upstream.aclose()

    return JSONResponse(
        {"model": model, "response": text, "done": True},
    )
