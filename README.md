# Ollama Auth Proxy

Small FastAPI proxy that protects an existing Ollama HTTP server with a bearer token. It does not start Ollama.

## Run

```bash
uv sync --extra dev
cp .env.example .env
# Edit .env and set API_TOKEN, then run:
uv run python -m ollama_proxy
```

Configure `API_TOKEN`, `OLLAMA_URL`, `PORT`, and `OLLAMA_TIMEOUT_SECONDS` in `.env` or as environment variables. Every proxied request must include:

```text
Authorization: Bearer replace-with-a-secret
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
  -H 'Authorization: Bearer replace-with-a-secret'
```

Ollama streaming is passed through immediately. For generated text, include `"stream": true` in the JSON request:

```bash
curl http://127.0.0.1:8000/api/generate \
  -H 'Authorization: Bearer replace-with-a-secret' \
  -H 'Content-Type: application/json' \
  -d '{"model":"llama3","prompt":"Hello","stream":true}'
```

## Verify

```bash
uv run pytest
```

## Run with Docker

With Ollama running on the host machine, set `API_TOKEN` in `.env` and use:

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
  -H 'Authorization: Bearer replace-with-a-secret'

sudo ss -ltnp | grep ':8000'
```
