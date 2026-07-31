import hmac
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .config import Settings

_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def _forward_headers(headers: httpx.Headers | dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in _HOP_BY_HOP_HEADERS
        and key.lower() not in {"host", "content-length", "authorization"}
    }


def _is_authorized(request: Request, expected_token: str) -> bool:
    if not expected_token:
        return False
    value = request.headers.get("authorization", "")
    scheme, separator, token = value.partition(" ")
    return separator == " " and scheme.lower() == "bearer" and hmac.compare_digest(token, expected_token)


def create_app(settings: Settings | None = None, client: httpx.AsyncClient | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not resolved_settings.api_token:
            raise RuntimeError("API_TOKEN must be set")
        if not resolved_settings.ollama_url:
            raise RuntimeError("OLLAMA_URL must be set")
        owns_client = client is None
        if owns_client:
            app.state.client = httpx.AsyncClient(timeout=resolved_settings.timeout_seconds)
        else:
            app.state.client = client
        yield
        if owns_client:
            await app.state.client.aclose()

    app = FastAPI(title="Ollama Auth Proxy", lifespan=lifespan)
    if client is not None:
        app.state.client = client

    @app.api_route("", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    async def proxy(request: Request, path: str = "") -> Response:
        if not _is_authorized(request, resolved_settings.api_token):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})

        target = f"{resolved_settings.ollama_url}/{path}"
        if request.url.query:
            target = f"{target}?{request.url.query}"

        try:
            upstream_request = app.state.client.build_request(
                request.method,
                target,
                headers=_forward_headers(request.headers),
                content=await request.body(),
            )
            upstream = await app.state.client.send(upstream_request, stream=True)
        except httpx.TimeoutException:
            return JSONResponse({"detail": "Ollama request timed out"}, status_code=504)
        except httpx.RequestError:
            return JSONResponse({"detail": "Ollama server unavailable"}, status_code=502)

        async def body():
            try:
                if upstream.is_stream_consumed:
                    yield upstream.content
                else:
                    async for chunk in upstream.aiter_raw():
                        yield chunk
            finally:
                await upstream.aclose()

        response_headers = _forward_headers(upstream.headers)
        response_headers.update({
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })

        return StreamingResponse(
            body(),
            status_code=upstream.status_code,
            headers=response_headers,
            media_type=upstream.headers.get("content-type"),
        )

    return app


app = create_app()
