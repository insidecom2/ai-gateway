import httpx
import libsql_client
import pytest

from ollama_proxy.turso import TursoAdapter, TursoConfigurationError


class FakeClient:
    def __init__(self):
        self.closed = False
        self.executed = []

    async def execute(self, statement, args=None):
        self.executed.append((statement, args))
        return "result"

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_connects_from_environment_and_forwards_execute():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "type": "ok",
                        "response": {
                            "type": "execute",
                            "result": {
                                "cols": [{"name": "answer"}],
                                "rows": [[{"type": "integer", "value": "42"}]],
                                "affected_row_count": 0,
                                "last_insert_rowid": None,
                            },
                        },
                    },
                    {"type": "ok", "response": {"type": "close"}},
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TursoAdapter.from_env(
        {
            "TURSO_DATABASE_URL": "libsql://example.turso.io",
            "TURSO_AUTH_TOKEN": "secret-token",
        },
        http_client=client,
    )

    async with adapter as connected:
        result = await connected.execute("SELECT ? AS answer", [1])

    assert result.columns == ("answer",)
    assert result.rows[0]["answer"] == 42
    assert str(requests[0].url) == "https://example.turso.io/v2/pipeline"
    assert requests[0].headers["authorization"] == "Bearer secret-token"
    request_body = requests[0].content.decode()
    assert '"sql":"SELECT ? AS answer"' in request_body
    assert '"value":"1"' in request_body
    assert adapter.connected is False
    await client.aclose()


@pytest.mark.asyncio
async def test_connect_is_idempotent():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    adapter = TursoAdapter("libsql://example.turso.io", "secret-token", http_client=client)

    await adapter.connect()
    await adapter.connect()

    await adapter.close()
    await client.aclose()


@pytest.mark.asyncio
async def test_local_sqlite_url_does_not_require_auth(monkeypatch):
    fake_client = FakeClient()
    factory_calls = []

    def create_client(url, *, auth_token=None):
        factory_calls.append((url, auth_token))
        return fake_client

    monkeypatch.setattr(libsql_client, "create_client", create_client)
    adapter = TursoAdapter("file:local.db")

    await adapter.connect()
    await adapter.close()

    assert factory_calls == [("file:local.db", None)]


@pytest.mark.asyncio
async def test_remote_query_error_is_raised():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "type": "error",
                            "error": {"message": "no such table", "code": "SQL"},
                        }
                    ]
                },
            )
        )
    )
    adapter = TursoAdapter("libsql://example.turso.io", "secret-token", http_client=client)

    await adapter.connect()
    with pytest.raises(libsql_client.LibsqlError, match="no such table"):
        await adapter.execute("SELECT * FROM missing")
    await adapter.close()
    await client.aclose()


@pytest.mark.asyncio
async def test_remote_connection_requires_url_and_token():
    with pytest.raises(TursoConfigurationError, match="TURSO_DATABASE_URL"):
        await TursoAdapter("", "secret-token").connect()

    with pytest.raises(TursoConfigurationError, match="TURSO_AUTH_TOKEN"):
        await TursoAdapter("libsql://example.turso.io").connect()


@pytest.mark.asyncio
async def test_execute_requires_connection():
    with pytest.raises(RuntimeError, match="not connected"):
        await TursoAdapter("libsql://example.turso.io", "secret-token").execute("SELECT 1")
