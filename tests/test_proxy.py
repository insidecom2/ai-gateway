import httpx
import pytest
from httpx import ASGITransport, MockTransport, Request, Response as HTTPXResponse

from ollama_proxy.app import create_app
from ollama_proxy.config import Settings


def make_app(handler, ollama_url="http://127.0.0.1:11434"):
    client = httpx.AsyncClient(transport=MockTransport(handler))
    return create_app(Settings(api_token="secret", ollama_url=ollama_url), client=client)


@pytest.mark.asyncio
async def test_requires_bearer_token():
    app = make_app(lambda _: HTTPXResponse(200))
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.get("/api/tags")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_forwards_request_and_response():
    def handler(request: Request) -> HTTPXResponse:
        assert request.method == "POST"
        assert str(request.url) == "http://ollama:11434/api/generate?stream=false"
        assert request.headers["x-client"] == "test"
        assert "authorization" not in request.headers
        assert request.content == b'{"model":"llama3"}'
        return HTTPXResponse(201, headers={"content-type": "application/json"}, content=b'{"ok":true}')

    app = make_app(handler, ollama_url="http://ollama:11434")
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate?stream=false",
            headers={"Authorization": "Bearer secret", "X-Client": "test"},
            content=b'{"model":"llama3"}',
        )
    assert response.status_code == 201
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_streams_upstream_response():
    app = make_app(lambda _: HTTPXResponse(200, headers={"content-type": "application/x-ndjson"}, content=b'{"response":"hi"}\n'))
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": "Bearer secret"},
            json={"model": "llama3", "prompt": "hello", "stream": True},
        )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-ndjson"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.text == '{"response":"hi"}\n'


@pytest.mark.asyncio
async def test_maps_upstream_errors():
    async def handler(_: Request) -> HTTPXResponse:
        raise httpx.ConnectError("down")

    app = make_app(handler)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.get("/api/tags", headers={"Authorization": "Bearer secret"})
    assert response.status_code == 502
