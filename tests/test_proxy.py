import json
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from httpx import ASGITransport, MockTransport, Request, Response as HTTPXResponse

from ollama_proxy.app import create_app
from ollama_proxy.config import Settings
from ollama_proxy.models import MODEL_GEMMA_CELESTIAL

TOKEN_SECRET = "a-32-byte-minimum-hs256-test-key"


def bearer_token(*, secret=TOKEN_SECRET, algorithm="HS256", payload=None):
    claims = {"exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
    if payload:
        claims.update(payload)
    return jwt.encode(claims, secret, algorithm=algorithm)


def make_app(handler, ollama_url="http://127.0.0.1:11434", gemini_api_key=""):
    client = httpx.AsyncClient(transport=MockTransport(handler))
    return create_app(
        Settings(api_token=TOKEN_SECRET, ollama_url=ollama_url, gemini_api_key=gemini_api_key),
        client=client,
    )


@pytest.mark.asyncio
async def test_requires_bearer_token():
    app = make_app(lambda _: HTTPXResponse(200))
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.get("/api/tags")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rejects_short_hs256_signing_key_at_startup():
    app = create_app(Settings(api_token="too-short", ollama_url="http://ollama:11434"))
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        async with app.router.lifespan_context(app):
            pass


@pytest.mark.asyncio
async def test_rejects_invalid_jwts_without_calling_upstream():
    def handler(_: Request) -> HTTPXResponse:
        raise AssertionError("invalid JWT must not reach upstream")

    app = make_app(handler)
    invalid_tokens = [
        bearer_token(secret="a-different-32-byte-hs256-test-key"),
        jwt.encode({}, TOKEN_SECRET, algorithm="HS256"),
        bearer_token(payload={"exp": datetime.now(timezone.utc) - timedelta(seconds=1)}),
        bearer_token(
            algorithm="HS384",
            secret="a" * 64,
        ),
        TOKEN_SECRET,
    ]
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        for token in invalid_tokens:
            response = await client.get("/api/tags", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 401
            assert response.headers["www-authenticate"] == "Bearer"


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
            headers={
                "Authorization": (
                    f"Bearer {bearer_token(payload={'iss': 'jantraastro', 'aud': 'ollama', 'sub': 'next-fortune'})}"
                ),
                "X-Client": "test",
            },
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
            headers={"Authorization": f"Bearer {bearer_token()}"},
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
        response = await client.get("/api/tags", headers={"Authorization": f"Bearer {bearer_token()}"})
    assert response.status_code == 502


class FakeTursoAdapter:
    def __init__(self, rows):
        self._rows = rows

    @classmethod
    def from_env(cls, *args, **kwargs):
        return cls(FakeTursoAdapter._rows)

    async def connect(self):
        return self

    async def close(self):
        pass

    async def execute(self, statement, args=None):
        if "astrology_systems" in str(statement):
            return _ResultSet(
                [
                    {
                        "display_name": "โหราศาสตร์ไทย",
                        "description": "ตัวอย่าง",
                        "house_method": "Whole Sign",
                        "ayanamsa_note": "Lahiri",
                    }
                ]
            )
        return _ResultSet(self._rows)


class _ResultSet:
    def __init__(self, rows):
        self.columns = list(rows[0].keys()) if rows else []
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)


@pytest.mark.asyncio
async def test_gemma_celestial_runs_astrology_pipeline(monkeypatch):
    import ollama_proxy.astrology as astrology

    fake = FakeTursoAdapter(
        [
            {
                "content": "ภพที่ 10 ใช้เป็นกรอบพิจารณาหน้าที่การงาน ชื่อเสียง บทบาทสาธารณะ",
                "content_summary": "ภพ 10 งาน",
                "category": "house",
                "topic": "house_meaning",
                "planet_code": None,
                "planet_name": None,
                "house_number": "10",
                "zodiac_sign": None,
                "keywords_json": "[]",
                "chunk_key": "house.10.career",
                "document_key": "doc1",
                "source_locator": "seed:house.10.career",
            }
        ]
    )
    FakeTursoAdapter._rows = fake._rows
    monkeypatch.setattr(astrology, "TursoAdapter", FakeTursoAdapter)

    def handler(request: Request) -> HTTPXResponse:
        body = request.content.decode()
        assert "ลัคนา" in body
        assert "ภพที่ 10" in body
        assert "อยากรู้ดวงการงาน" in body
        return HTTPXResponse(200, json={"model": MODEL_GEMMA_CELESTIAL, "response": "ดวงการงาน..."})

    app = make_app(handler)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={
                "model": MODEL_GEMMA_CELESTIAL,
                "prompt": "อยากรู้ดวงการงานปีนี้เป็นอย่างไร",
                "birth_date": "1990-08-15",
                "birth_time": "06:30",
                "birth_place": "กรุงเทพ",
                "stream": False,
            },
        )
    assert response.status_code == 200
    assert response.json()["response"] == "ดวงการงาน..."


@pytest.mark.asyncio
async def test_gemma_celestial_invalid_birth_place_returns_400():
    async def handler(_: Request) -> HTTPXResponse:
        raise AssertionError("should not reach Ollama")

    app = make_app(handler)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={
                "model": MODEL_GEMMA_CELESTIAL,
                "prompt": "ดูดวง",
                "birth_date": "1990-08-15",
                "birth_time": "06:30",
                "birth_place": "ไม่มีเมืองนี้",
                "stream": False,
            },
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_other_models_bypass_astrology(monkeypatch):
    import ollama_proxy.astrology as astrology

    called = False

    async def fake_run(*args, **kwargs):
        nonlocal called
        called = True
        return HTTPXResponse(200, json={"response": "nope"})

    monkeypatch.setattr(astrology, "run_astrology", fake_run)

    def handler(request: Request) -> HTTPXResponse:
        assert request.content == b'{"model":"llama3"}'
        return HTTPXResponse(200, json={"response": "hi"})

    app = make_app(handler)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={"model": "llama3"},
        )
    assert response.status_code == 200
    assert response.json() == {"response": "hi"}
    assert called is False


@pytest.mark.asyncio
async def test_explicit_astrology_false_bypasses_default_pipeline_and_is_not_forwarded(monkeypatch):
    import ollama_proxy.app as proxy_app

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("explicit astrology=false should bypass the pipeline")

    monkeypatch.setattr(proxy_app, "run_astrology", fail_if_called)

    def handler(request: Request) -> HTTPXResponse:
        assert json.loads(request.content) == {"model": MODEL_GEMMA_CELESTIAL, "prompt": "already enriched"}
        return HTTPXResponse(200, json={"response": "ok"})

    app = make_app(handler)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={"model": MODEL_GEMMA_CELESTIAL, "prompt": "already enriched", "astrology": False},
        )
    assert response.status_code == 200
    assert response.json() == {"response": "ok"}


@pytest.mark.asyncio
async def test_gemini_model_uses_gemini_and_normalizes_response():
    def handler(request: Request) -> HTTPXResponse:
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.url.path.endswith("/models/gemini-test:generateContent")
        assert request.headers["x-goog-api-key"] == "secret-gemini-key"
        body = json.loads(request.content)
        assert body["contents"][0]["parts"][0]["text"] == "hello"
        assert body["systemInstruction"]["parts"][0]["text"] == "be concise"
        return HTTPXResponse(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "hi from Gemini"}]}}]},
        )

    app = make_app(handler, gemini_api_key="secret-gemini-key")
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={"model": "gemini-test", "prompt": "hello", "system": "be concise"},
        )
    assert response.status_code == 200
    assert response.json() == {"model": "gemini-test", "response": "hi from Gemini", "done": True}


@pytest.mark.asyncio
async def test_gemini_chat_maps_messages_options_and_response_shape():
    def handler(request: Request) -> HTTPXResponse:
        body = json.loads(request.content)
        assert body["contents"] == [
            {"role": "user", "parts": [{"text": "hello"}]},
            {"role": "model", "parts": [{"text": "Hi there"}]},
            {"role": "user", "parts": [{"text": "continue"}]},
        ]
        assert body["systemInstruction"]["parts"] == [{"text": "be helpful"}]
        assert body["generationConfig"]["maxOutputTokens"] == 321
        return HTTPXResponse(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "Gemini chat answer"}]}}]},
        )

    app = make_app(handler, gemini_api_key="secret-gemini-key")
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/chat",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={
                "model": "gemini-test",
                "messages": [
                    {"role": "system", "content": "be helpful"},
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "Hi there"},
                    {"role": "user", "content": "continue"},
                ],
                "options": {"num_predict": 321},
                "stream": False,
            },
        )
    assert response.status_code == 200
    assert response.json() == {
        "model": "gemini-test",
        "message": {"role": "assistant", "content": "Gemini chat answer"},
        "done": True,
    }


@pytest.mark.asyncio
async def test_gemini_chat_stream_uses_ollama_chat_chunk_shape():
    def handler(_: Request) -> HTTPXResponse:
        return HTTPXResponse(
            200,
            headers={"content-type": "text/event-stream"},
            content=b'data: {"candidates":[{"content":{"parts":[{"text":"hello"}]}}]}\n\n',
        )

    app = make_app(handler, gemini_api_key="secret-gemini-key")
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/chat",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={"model": "gemini-test", "messages": [{"role": "user", "content": "hello"}], "stream": True},
        )
    chunks = [json.loads(line) for line in response.text.splitlines()]
    assert response.status_code == 200
    assert chunks[0]["message"] == {"role": "assistant", "content": "hello"}
    assert chunks[0]["done"] is False
    assert chunks[-1]["done"] is True


@pytest.mark.asyncio
async def test_ollama_chat_requests_keep_forwarding_to_ollama():
    def handler(request: Request) -> HTTPXResponse:
        assert str(request.url) == "http://ollama:11434/api/chat"
        assert request.content == b'{"model":"llama3","messages":[{"role":"user","content":"hello"}]}'
        return HTTPXResponse(200, json={"message": {"role": "assistant", "content": "hi"}, "done": True})

    app = make_app(handler, ollama_url="http://ollama:11434")
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/chat",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={"model": "llama3", "messages": [{"role": "user", "content": "hello"}]},
        )
    assert response.status_code == 200
    assert response.json()["message"]["content"] == "hi"


@pytest.mark.asyncio
async def test_gemini_request_without_key_does_not_call_upstream():
    def handler(_: Request) -> HTTPXResponse:
        raise AssertionError("Gemini request must not reach upstream without a key")

    app = make_app(handler)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={"model": "gemini-test", "prompt": "hello"},
        )
    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]


@pytest.mark.asyncio
async def test_gemini_stream_is_normalized_to_ollama_ndjson():
    def handler(request: Request) -> HTTPXResponse:
        assert request.url.path.endswith("/models/gemini-test:streamGenerateContent")
        assert request.url.params.get("alt") == "sse"
        return HTTPXResponse(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                b'data: {"candidates":[{"content":{"parts":[{"text":"first"}]}}]}\n\n'
                b'data: {"candidates":[{"content":{"parts":[{"text":" second"}]}}]}\n\n'
            ),
        )

    app = make_app(handler, gemini_api_key="secret-gemini-key")
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={"model": "gemini-test", "prompt": "hello", "stream": True},
        )
    chunks = [json.loads(line) for line in response.text.splitlines()]
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert [chunk["response"] for chunk in chunks] == ["first", " second", ""]
    assert chunks[-1]["done"] is True


@pytest.mark.asyncio
async def test_gemini_upstream_error_does_not_expose_api_key():
    def handler(_: Request) -> HTTPXResponse:
        return HTTPXResponse(403, json={"error": {"message": "denied"}})

    secret = "secret-gemini-key"
    app = make_app(handler, gemini_api_key=secret)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={"model": "gemini-test", "prompt": "hello"},
        )
    assert response.status_code == 502
    assert secret not in response.text


@pytest.mark.asyncio
async def test_gemini_malformed_upstream_response_is_not_reported_as_success():
    def handler(_: Request) -> HTTPXResponse:
        return HTTPXResponse(200, json={"unexpected": "shape"})

    app = make_app(handler, gemini_api_key="secret-gemini-key")
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={"model": "gemini-test", "prompt": "hello"},
        )
    assert response.status_code == 502
    assert "invalid response" in response.json()["detail"]


@pytest.mark.asyncio
async def test_gemini_timeout_returns_gateway_timeout_without_key_exposure():
    def handler(request: Request) -> HTTPXResponse:
        raise httpx.ReadTimeout("timed out", request=request)

    secret = "secret-gemini-key"
    app = make_app(handler, gemini_api_key=secret)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={"model": "gemini-test", "prompt": "hello"},
        )
    assert response.status_code == 504
    assert secret not in response.text


@pytest.mark.asyncio
async def test_invalid_jwt_does_not_call_gemini():
    def handler(_: Request) -> HTTPXResponse:
        raise AssertionError("invalid JWT must not reach Gemini")

    app = make_app(handler, gemini_api_key="secret-gemini-key")
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": "Bearer invalid"},
            json={"model": "gemini-test", "prompt": "hello"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_astrology_flag_routes_gemini_through_context_pipeline(monkeypatch):
    import ollama_proxy.astrology as astrology

    FakeTursoAdapter._rows = [
        {
            "content": "ภพที่ 10 ใช้พิจารณาการงาน",
            "content_summary": "ภพ 10 งาน",
            "category": "house",
            "topic": "house_meaning",
            "planet_code": None,
            "planet_name": None,
            "house_number": "10",
            "zodiac_sign": None,
            "keywords_json": "[]",
            "chunk_key": "house.10.career",
            "document_key": "doc1",
            "source_locator": "seed:house.10.career",
        }
    ]
    monkeypatch.setattr(astrology, "TursoAdapter", FakeTursoAdapter)

    def handler(request: Request) -> HTTPXResponse:
        body = json.loads(request.content)
        prompt = body["contents"][0]["parts"][0]["text"]
        assert "ดวงกำเนิด" in prompt
        assert "ภพที่ 10 ใช้พิจารณาการงาน" in prompt
        assert "อยากรู้ดวงการงาน" in prompt
        assert body["systemInstruction"]["parts"][0]["text"] == astrology.SYSTEM_PROMPT
        return HTTPXResponse(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "ดวงการงานจาก Gemini"}]}}]},
        )

    app = make_app(handler, gemini_api_key="secret-gemini-key")
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={
                "model": "gemini-test",
                "prompt": "อยากรู้ดวงการงาน",
                "astrology": True,
                "birth_date": "1990-08-15",
                "birth_time": "06:30",
                "birth_place": "กรุงเทพ",
            },
        )
    assert response.status_code == 200
    assert response.json()["response"] == "ดวงการงานจาก Gemini"


@pytest.mark.asyncio
async def test_gemini_chat_astrology_uses_messages_and_returns_chat_response(monkeypatch):
    import ollama_proxy.astrology as astrology

    FakeTursoAdapter._rows = [
        {
            "content": "ความรู้โหราศาสตร์สำหรับคำถามนี้",
            "content_summary": "ตัวอย่าง",
            "category": "general",
            "topic": "career",
            "planet_code": None,
            "planet_name": None,
            "house_number": None,
            "zodiac_sign": None,
            "keywords_json": "[]",
            "chunk_key": "career.example",
            "document_key": "doc1",
            "source_locator": "seed:career.example",
        }
    ]
    monkeypatch.setattr(astrology, "TursoAdapter", FakeTursoAdapter)

    def handler(request: Request) -> HTTPXResponse:
        body = json.loads(request.content)
        prompt = body["contents"][0]["parts"][0]["text"]
        assert "อยากรู้ดวงการงาน" in prompt
        assert "ความรู้โหราศาสตร์สำหรับคำถามนี้" in prompt
        assert body["generationConfig"]["maxOutputTokens"] == 700
        return HTTPXResponse(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "ดวงจาก Gemini chat"}]}}]},
        )

    app = make_app(handler, gemini_api_key="secret-gemini-key")
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/chat",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={
                "model": "gemini-test",
                "messages": [{"role": "user", "content": "อยากรู้ดวงการงาน"}],
                "astrology": True,
                "options": {"num_predict": 700},
                "stream": False,
            },
        )
    assert response.status_code == 200
    assert response.json() == {
        "model": "gemini-test",
        "message": {"role": "assistant", "content": "ดวงจาก Gemini chat"},
        "done": True,
    }
