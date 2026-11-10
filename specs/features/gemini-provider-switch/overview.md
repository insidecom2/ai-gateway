# Gemini Provider Switching

## Goal

Allow authenticated clients of the existing Ollama-compatible proxy to select
Google Gemini or Ollama by the model name in a generation request.

## Scope

- On `POST /api/generate`, route model names beginning with `gemini-` to the
  Gemini API; route all other model names to the configured Ollama server.
- Support ordinary text-generation requests and the existing astrology flow
  (chart calculation and Turso knowledge context) with either provider.
- Preserve automatic astrology routing for the existing configured astrology
  model, with an explicit boolean `astrology` field to select or skip that
  pipeline for a request.
- Preserve the proxy's Ollama-compatible response format, including
  non-streaming and streaming generation responses.
- Read Gemini credentials from `GEMINI_API_KEY`; fail clearly when a Gemini
  request is made without a configured key.
- Keep current JWT authentication and existing Ollama behavior.

## Out of Scope

- A frontend or UI for choosing providers.
- Gemini support for Ollama management routes such as `/api/tags` or
  `/api/pull`; those routes continue to use the configured Ollama server.
- Automatic fallback between providers.
- Changes to the astrology calculations, knowledge retrieval, or database.
- Adding a new SDK dependency; the existing HTTP client can call Gemini's
  REST API.

## Acceptance Criteria

1. Given an authenticated `POST /api/generate` request with a Gemini model
   name and configured `GEMINI_API_KEY`, when generation is requested, then
   the proxy calls Gemini and returns an Ollama-compatible generation payload.
2. Given an authenticated request with an Ollama model name, when generation
   is requested, then the proxy continues to forward it to Ollama unchanged.
3. Given a Gemini request without `GEMINI_API_KEY`, when generation is
   requested, then the proxy returns a clear configuration error and does not
   call either provider.
4. Given a Gemini request with `stream: true`, when Gemini emits streamed
   content, then the proxy returns Ollama-compatible NDJSON chunks and a final
   completion chunk.
5. Given an astrology request using a Gemini model name with
   `"astrology": true`, when chart and knowledge context are available, then
   that context is included in the Gemini prompt and the response is returned
   in the standard generation format.
6. Given a Gemini upstream error or timeout, when generation is requested,
   then the proxy returns a clear upstream error without exposing the API key.
7. Given any request without a valid bearer JWT, when it reaches the proxy,
   then existing authentication rejects it before calling either provider.
8. Given a request with `"astrology": false`, when it uses the configured
   astrology model, then the proxy skips its astrology pipeline and removes
   the proxy-only field before forwarding the request to Ollama.

## API Candidates

- Existing endpoint: `POST /api/generate`.
- Existing request field: `model`; the `gemini-` prefix selects Gemini, and
  other names select Ollama.
- Existing `stream` field controls streaming for either provider.
- If `astrology` is a boolean, it explicitly selects whether to run the
  astrology pipeline; otherwise the configured astrology model continues to
  invoke it automatically.
- Configuration: `GEMINI_API_KEY` environment variable.

## Event Flow

1. Authenticate the bearer JWT using the existing proxy boundary.
2. Parse the generation request and inspect its model name.
3. If the model starts with `gemini-`, use Gemini; otherwise use Ollama.
4. When `astrology` is an explicit boolean, follow it; otherwise retain the
   configured astrology model's automatic routing. If selected, compute chart
   data and fetch knowledge context, then build the existing astrology prompt
   for the chosen provider.
5. Convert provider output to the Ollama-compatible generation response,
   including normalized streaming chunks when requested.

## Edge Cases

- Empty or missing model is treated according to the current Ollama request
  behavior; Gemini is selected only by a `gemini-` prefix.
- Missing Gemini key must not fall back to Ollama.
- Gemini non-success responses, malformed responses, and timeouts must not
  leak credentials or return a false successful generation.
- Streaming should terminate cleanly and emit a final `done` indication.

## Affected Areas

- `src/ollama_proxy/app.py`: provider routing and Gemini configuration wiring.
- `src/ollama_proxy/config.py`: Gemini API key setting.
- `src/ollama_proxy/astrology.py`: selected-provider generation for astrology.
- `env.example`, README: Gemini configuration and usage.
- `tests/test_proxy.py`: provider routing, compatibility, streaming, and errors.

## User Decisions

- Select provider using the model name: `gemini-...` routes to Gemini; other
  model names route to Ollama.
- Gemini should support both ordinary requests and the existing astrology
  pipeline.
- Gemini requests should support streaming.
- An explicit `astrology` boolean overrides automatic routing for the
  configured astrology model. The CLI sets `false` because it builds context
  itself.
