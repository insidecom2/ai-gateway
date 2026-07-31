<<<<<<< HEAD
# ai-gateway
Python gateway for ollama
=======
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

Compose maps `host.docker.internal:11434` to the host, so the container can call local Ollama. To use another endpoint in Docker, set `OLLAMA_URL_DOCKER`; keep `OLLAMA_URL` for direct, non-container runs.
>>>>>>> c11a6ca (init project)
