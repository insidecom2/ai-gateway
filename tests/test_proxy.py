import json
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from httpx import ASGITransport, MockTransport, Request, Response as HTTPXResponse

from ollama_proxy.app import create_app
from ollama_proxy.config import Settings

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
async def test_astrology_flag_runs_pipeline_for_any_model(monkeypatch):
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
        return HTTPXResponse(200, json={"model": "llama3", "response": "ดวงการงาน..."})

    app = make_app(handler)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={
                "model": "llama3",
                "prompt": "อยากรู้ดวงการงานปีนี้เป็นอย่างไร",
                "astrology": True,
                "birth_date": "1990-08-15",
                "birth_time": "06:30",
                "birth_place": "กรุงเทพ",
                "stream": False,
            },
        )
    assert response.status_code == 200
    assert response.json()["response"] == "ดวงการงาน..."


@pytest.mark.asyncio
async def test_astrology_flag_invalid_birth_place_returns_400():
    async def handler(_: Request) -> HTTPXResponse:
        raise AssertionError("should not reach Ollama")

    app = make_app(handler)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={
                "model": "llama3",
                "prompt": "ดูดวง",
                "astrology": True,
                "birth_date": "1990-08-15",
                "birth_time": "06:30",
                "birth_place": "ไม่มีเมืองนี้",
                "stream": False,
            },
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_birth_date_only_uses_approximate_noon_and_defaults_birth_place_to_bangkok(monkeypatch):
    import ollama_proxy.astrology as astrology

    monkeypatch.setattr(astrology, "TursoAdapter", FakeTursoAdapter)
    charts = []

    async def fake_fetch_context(_adapter, _query, _limit, chart=None):
        charts.append(chart)
        return []

    monkeypatch.setattr(astrology, "fetch_context", fake_fetch_context)

    def handler(request: Request) -> HTTPXResponse:
        payload = json.loads(request.content)
        assert "เกิดวันที่ 1990-08-15 ไม่ทราบเวลา" in payload["prompt"]
        assert "ใช้เวลา 12:00 น." in payload["prompt"]
        assert "13.7563" in payload["prompt"]
        assert "100.5018" in payload["prompt"]
        assert "ห้ามสรุปลัคนาหรือเรือน" in payload["prompt"]
        return HTTPXResponse(200, json={"response": "ภาพรวมตำแหน่งดาวโดยประมาณ"})

    app = make_app(handler)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={
                "model": "llama3",
                "prompt": "ช่วยดูดวงการงาน",
                "astrology": True,
                "birth_date": "1990-08-15",
            },
        )

    assert response.status_code == 200
    assert response.json()["response"] == "ภาพรวมตำแหน่งดาวโดยประมาณ"
    assert len(charts) == 1
    assert charts[0]["birth_time_assumed"] is True
    assert charts[0]["birth_time"] is None
    assert charts[0]["ascendant"] is None
    assert all(planet["house"] is None for planet in charts[0]["planets"].values())


@pytest.mark.asyncio
async def test_birth_date_is_required_for_astrology():
    def handler(_: Request) -> HTTPXResponse:
        raise AssertionError("a request without birth_date must not call the provider")

    app = make_app(handler)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={"model": "llama3", "prompt": "ช่วยดูดวงการงาน", "astrology": True},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "birth_date is required for astrology"


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
async def test_astrology_false_bypasses_pipeline_and_is_not_forwarded(monkeypatch):
    import ollama_proxy.app as proxy_app

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("explicit astrology=false should bypass the pipeline")

    monkeypatch.setattr(proxy_app, "run_astrology", fail_if_called)

    def handler(request: Request) -> HTTPXResponse:
        assert json.loads(request.content) == {"model": "llama3", "prompt": "already enriched"}
        return HTTPXResponse(200, json={"response": "ok"})

    app = make_app(handler)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={"model": "llama3", "prompt": "already enriched", "astrology": False},
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
                "birth_date": "1990-08-15",
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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Tell me about my career this year", "English"),
        ("请分析我的事业运势", "Chinese"),
        ("ช่วยดูดวงการงานให้หน่อย", "Thai"),
        ("OK", "Thai"),
        ("Hi 你好", "Thai"),
    ],
)
def test_detect_response_language(text, expected):
    from ollama_proxy.astrology import detect_response_language

    assert detect_response_language(text) == expected


def test_astrology_prompt_explains_rag_content_without_source_citations():
    from ollama_proxy.astrology import SYSTEM_PROMPT, build_prompt

    prompt = build_prompt(
        "วิเคราะห์เรื่องงาน",
        [
            {
                "content": "ดาวพุธสัมพันธ์กับการสื่อสารและการเจรจา",
                "content_summary": "ดาวพุธ",
                "category": "planet",
                "topic": "communication",
                "planet_name": "พุธ",
                "keywords_json": '["งาน"]',
                "document_key": "private-document",
                "chunk_key": "private-chunk",
                "source_locator": "private-locator",
            }
        ],
    )

    assert "ดาวพุธสัมพันธ์กับการสื่อสารและการเจรจา" in prompt
    assert "private-document" not in prompt
    assert "private-chunk" not in prompt
    assert "private-locator" not in prompt
    assert "keywords_json" not in prompt
    assert "เครื่องหมายอ้างอิงแบบวงเล็บเหลี่ยม" in SYSTEM_PROMPT
    assert "[1]" not in SYSTEM_PROMPT
    assert "[1]" not in prompt
    assert "คำตอบเป็นภาพรวม" in prompt


@pytest.mark.asyncio
async def test_english_astrology_question_is_translated_before_rag_and_answer_language_is_requested(monkeypatch):
    import ollama_proxy.astrology as astrology

    FakeTursoAdapter._rows = []
    monkeypatch.setattr(astrology, "TursoAdapter", FakeTursoAdapter)
    retrieved_queries = []

    async def fake_fetch_context(_adapter, query, _limit, chart=None):
        retrieved_queries.append(query)
        return [
            {
                "content": "ภพที่ 10 ใช้พิจารณาหน้าที่การงาน",
                "display_name": "โหราศาสตร์ไทย",
                "description": "ตัวอย่าง",
                "house_method": "Whole Sign",
                "ayanamsa_note": "Lahiri",
                "document_key": "private-doc",
                "chunk_key": "private-chunk",
                "source_locator": "private-source",
                "keywords_json": "[]",
            }
        ]

    monkeypatch.setattr(astrology, "fetch_context", fake_fetch_context)
    request_count = 0

    def handler(request: Request) -> HTTPXResponse:
        nonlocal request_count
        request_count += 1
        payload = json.loads(request.content)
        if request_count == 1:
            assert "ผู้แปล" in payload["system"]
            assert "Tell me about my career this year" in payload["prompt"]
            return HTTPXResponse(200, json={"response": "ช่วยวิเคราะห์เรื่องการงานของฉันในปีนี้"})

        prompt = payload["prompt"]
        assert "ช่วยวิเคราะห์เรื่องการงานของฉันในปีนี้" in prompt
        assert "Tell me about my career this year" not in prompt
        assert "ภาษา English" in prompt
        assert "ภพที่ 10 ใช้พิจารณาหน้าที่การงาน" in prompt
        assert "private-doc" not in prompt
        assert "private-chunk" not in prompt
        assert "private-source" not in prompt
        assert "document_key" not in payload["system"]
        return HTTPXResponse(200, json={"response": "Your career outlook is shaped by your public role."})

    app = make_app(handler)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={
                "model": "llama3",
                "prompt": "Tell me about my career this year",
                "astrology": True,
                "birth_date": "1990-08-15",
                "stream": False,
            },
        )

    assert response.status_code == 200
    assert response.json()["response"] == "Your career outlook is shaped by your public role."
    assert retrieved_queries == ["ช่วยวิเคราะห์เรื่องการงานของฉันในปีนี้"]
    assert request_count == 2


@pytest.mark.asyncio
async def test_chinese_gemini_astrology_translates_query_and_requests_chinese_answer(monkeypatch):
    import ollama_proxy.astrology as astrology

    FakeTursoAdapter._rows = []
    monkeypatch.setattr(astrology, "TursoAdapter", FakeTursoAdapter)
    retrieved_queries = []

    async def fake_fetch_context(_adapter, query, _limit, chart=None):
        retrieved_queries.append(query)
        return [{"content": "ภพที่ 10 ใช้พิจารณาหน้าที่การงาน"}]

    monkeypatch.setattr(astrology, "fetch_context", fake_fetch_context)
    request_count = 0

    def handler(request: Request) -> HTTPXResponse:
        nonlocal request_count
        request_count += 1
        payload = json.loads(request.content)
        if request_count == 1:
            system = payload["systemInstruction"]["parts"][0]["text"]
            assert "ผู้แปล" in system
            assert "请分析我的事业运势" in payload["contents"][0]["parts"][0]["text"]
            return HTTPXResponse(
                200,
                json={"candidates": [{"content": {"parts": [{"text": "ช่วยวิเคราะห์ดวงการงานของฉัน"}]}}]},
            )

        system = payload["systemInstruction"]["parts"][0]["text"]
        prompt = payload["contents"][0]["parts"][0]["text"]
        assert system == astrology.SYSTEM_PROMPT
        assert "ช่วยวิเคราะห์ดวงการงานของฉัน" in prompt
        assert "ภาษา Chinese" in prompt
        assert "ภพที่ 10 ใช้พิจารณาหน้าที่การงาน" in prompt
        assert "document_key" not in prompt
        return HTTPXResponse(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "你的事业运势与公开角色有关。"}]}}]},
        )

    app = make_app(handler, gemini_api_key="secret-gemini-key")
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/chat",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={
                "model": "gemini-test",
                "messages": [{"role": "user", "content": "请分析我的事业运势"}],
                "astrology": True,
                "birth_date": "1990-08-15",
                "stream": False,
            },
        )

    assert response.status_code == 200
    assert response.json()["message"]["content"] == "你的事业运势与公开角色有关。"
    assert retrieved_queries == ["ช่วยวิเคราะห์ดวงการงานของฉัน"]
    assert request_count == 2


@pytest.mark.asyncio
async def test_chinese_ollama_chat_translates_query_and_requests_chinese_answer(monkeypatch):
    import ollama_proxy.astrology as astrology

    monkeypatch.setattr(astrology, "TursoAdapter", FakeTursoAdapter)
    retrieved_queries = []

    async def fake_fetch_context(_adapter, query, _limit, chart=None):
        retrieved_queries.append(query)
        return [{"content": "ภพที่ 10 ใช้พิจารณาหน้าที่การงาน"}]

    monkeypatch.setattr(astrology, "fetch_context", fake_fetch_context)
    request_count = 0

    def handler(request: Request) -> HTTPXResponse:
        nonlocal request_count
        request_count += 1
        payload = json.loads(request.content)
        if request_count == 1:
            assert request.url.path.endswith("/api/generate")
            assert "请分析我的事业运势" in payload["prompt"]
            return HTTPXResponse(200, json={"response": "ช่วยวิเคราะห์ดวงการงานของฉัน"})

        assert request.url.path.endswith("/api/chat")
        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][1]["content"].startswith("### ระบบโหราศาสตร์ที่ใช้")
        prompt = payload["messages"][1]["content"]
        assert "ช่วยวิเคราะห์ดวงการงานของฉัน" in prompt
        assert "ภาษา Chinese" in prompt
        assert "ภพที่ 10 ใช้พิจารณาหน้าที่การงาน" in prompt
        assert "source_locator" not in prompt
        return HTTPXResponse(200, json={"message": {"role": "assistant", "content": "你的事业运势与公开角色有关。"}})

    app = make_app(handler)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/chat",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={
                "model": "llama3",
                "messages": [{"role": "user", "content": "请分析我的事业运势"}],
                "astrology": True,
                "birth_date": "1990-08-15",
                "stream": False,
            },
        )

    assert response.status_code == 200
    assert response.json()["message"]["content"] == "你的事业运势与公开角色有关。"
    assert retrieved_queries == ["ช่วยวิเคราะห์ดวงการงานของฉัน"]
    assert request_count == 2


@pytest.mark.asyncio
async def test_translation_provider_failure_returns_gateway_error_without_rag_lookup():
    def handler(request: Request) -> HTTPXResponse:
        assert request.url.host == "generativelanguage.googleapis.com"
        return HTTPXResponse(503, json={"error": {"message": "temporarily unavailable"}})

    app = make_app(handler, gemini_api_key="secret-gemini-key")
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={
                "model": "gemini-test",
                "prompt": "How is my career?",
                "astrology": True,
                "birth_date": "1990-08-15",
            },
        )

    assert response.status_code == 502
    assert response.json() == {"detail": "ดูดวง pipeline error"}
    assert "temporarily unavailable" not in response.text
    assert "How is my career?" not in response.text


@pytest.mark.asyncio
async def test_astrology_streaming_keeps_ollama_ndjson_response_shape(monkeypatch):
    import ollama_proxy.astrology as astrology

    monkeypatch.setattr(astrology, "TursoAdapter", FakeTursoAdapter)

    async def empty_context(*_args, **_kwargs):
        return []

    monkeypatch.setattr(astrology, "fetch_context", empty_context)

    def handler(request: Request) -> HTTPXResponse:
        payload = json.loads(request.content)
        assert payload["stream"] is True
        assert "ภาษา Thai" in payload["prompt"]
        assert "source_locator" not in payload["prompt"]
        return HTTPXResponse(
            200,
            headers={"content-type": "application/x-ndjson"},
            content=b'{"response":"forecast","done":false}\n{"response":"","done":true}\n',
        )

    app = make_app(handler)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://proxy") as client:
        response = await client.post(
            "/api/generate",
            headers={"Authorization": f"Bearer {bearer_token()}"},
            json={
                "model": "llama3",
                "prompt": "ช่วยดูดวงการงาน",
                "astrology": True,
                "birth_date": "1990-08-15",
                "stream": True,
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.text == '{"response":"forecast","done":false}\n{"response":"","done":true}\n'
