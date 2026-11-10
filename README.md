# Ollama Auth Proxy

Small FastAPI proxy that protects an existing Ollama HTTP server with a bearer token. It does not start Ollama.

## Run

```bash
uv sync --extra dev
cp .env.example .env
# Edit .env and set API_TOKEN to a random value of at least 32 bytes, then run:
uv run python -m ollama_proxy
```

Configure `API_TOKEN`, `OLLAMA_URL`, `GEMINI_API_KEY` (when using Gemini), `PORT`, and `OLLAMA_TIMEOUT_SECONDS` in `.env` or as environment variables. `API_TOKEN` is the HS256 JWT signing secret and must contain at least 32 bytes; generate one with `openssl rand -hex 32`. Every proxied request must include a JWT signed with that secret and an unexpired `exp` claim:

```text
Authorization: Bearer <HS256-JWT>
```

## Turso adapter

The optional async Turso/libSQL adapter reads `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`. It is not required by the proxy itself; consumers can use it as a managed context:

```python
from ollama_proxy.turso import TursoAdapter

async with TursoAdapter.from_env() as database:
    result = await database.execute("SELECT 1")
```

Use a `file:` URL for a local SQLite database when needed. Remote Turso URLs require `TURSO_AUTH_TOKEN`.

Example:

```bash
curl http://127.0.0.1:8000/api/tags \
  -H 'Authorization: Bearer <HS256-JWT>'
```

Ollama streaming is passed through immediately. For generated text, include `"stream": true` in the JSON request:

```bash
curl http://127.0.0.1:8000/api/generate \
  -H 'Authorization: Bearer <HS256-JWT>' \
  -H 'Content-Type: application/json' \
  -d '{"model":"llama3","prompt":"Hello","stream":true}'
```

## Select Gemini or Ollama

For `POST /api/generate` and `POST /api/chat`, the model name selects the
provider: names beginning with `gemini-` are sent to Google's Gemini API, and
other model names continue to use Ollama. Set `GEMINI_API_KEY` to enable
Gemini. Gemini responses and streaming chunks use the matching Ollama response
format for each endpoint.

```bash
curl http://127.0.0.1:8000/api/generate \
  -H 'Authorization: Bearer <HS256-JWT>' \
  -H 'Content-Type: application/json' \
  -d '{"model":"gemini-2.5-flash","prompt":"Hello","stream":false}'
```

To run the existing chart and Turso context pipeline with a Gemini model, set
`"astrology": true` in the generation or chat request. For `/api/chat`, send
the question in `messages`. The configured astrology model continues to invoke
that pipeline automatically unless `astrology` is explicitly set to `false`.

```bash
curl http://127.0.0.1:8000/api/chat \
  -H 'Authorization: Bearer <HS256-JWT>' \
  -H 'Content-Type: application/json' \
  -d '{"model":"gemini-3.1-flash-lite","messages":[{"role":"user","content":"Hello"}],"stream":true,"options":{"num_predict":512}}'
```

For Gemini, `options.num_predict` maps to `generationConfig.maxOutputTokens`.

The `astrology_ask.py` CLI uses `PROXY_URL` (default `http://127.0.0.1:8000`)
and signs a short-lived JWT with `API_TOKEN`. Set the same `API_TOKEN` for the
proxy and CLI; it must be at least 32 bytes. The CLI can select Gemini with
`--model gemini-2.5-flash`.

## Verify

```bash
uv run pytest
```

## Run with Docker

With Ollama running on the host machine, set a 32-byte-or-longer `API_TOKEN` in `.env` and use:

```bash
docker compose up --build
```

The default Compose configuration publishes the proxy on host port `8000` and reaches host-side Ollama at `http://host.docker.internal:11434`. To use another endpoint in Docker, set `OLLAMA_URL_DOCKER`; keep `OLLAMA_URL` for direct, non-container runs.

### Ubuntu host networking

On some Ubuntu hosts, Docker bridge networking cannot reach `host.docker.internal`, even when Ollama listens on port `11434`. Use a Compose override to run the proxy on the host network instead:

```yaml
# docker-compose.ubuntu.yml
services:
  ollama-auth-proxy:
    network_mode: host
    ports: !reset []
    environment:
      OLLAMA_URL: http://127.0.0.1:11434
      HOST: 127.0.0.1
      PORT: 8000
```

Start the proxy with both Compose files:

```bash
docker compose -f docker-compose.yml -f docker-compose.ubuntu.yml up -d --build
```

With host networking, Docker does not display a `PORTS` mapping in `docker ps`; this is expected. The proxy listens directly on Ubuntu's port `8000`. Verify it with:

```bash
curl http://127.0.0.1:8000/api/tags \
  -H 'Authorization: Bearer <HS256-JWT>'

sudo ss -ltnp | grep ':8000'
```
