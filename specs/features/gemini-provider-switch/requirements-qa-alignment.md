# Requirements QA Alignment: Gemini Provider Switching

## Gate Status

- Status: Approved
- Reviewer Notes: The provider selection, scope, streaming behavior, required
  configuration, and failure behavior are observable and covered by API tests.
  No frontend or database work is required.

## Requirement Quality Review

| ID | Requirement | Quality | Issue | Resolution Needed |
|---|---|---|---|---|
| FR-001 | Route `gemini-...` generation requests to Gemini and other model names to Ollama. | Clear | None | None |
| FR-002 | Support Gemini for regular text generation and astrology context generation, selected with `astrology: true` for non-default astrology models. | Clear | None | None |
| FR-003 | Preserve the Ollama-compatible response format for both providers. | Clear | None | None |
| FR-004 | Normalize Gemini streaming into Ollama-compatible NDJSON. | Clear | None | None |
| FR-005 | Read Gemini credentials from `GEMINI_API_KEY`. | Clear | None | None |
| FR-006 | Let an explicit boolean `astrology` request field override the configured astrology model's automatic routing, and strip the proxy-only false flag before Ollama forwarding. | Clear | None | None |
| NFR-001 | Preserve existing JWT authentication before provider access. | Clear | None | None |
| NFR-002 | Do not expose Gemini credentials in errors or logs. | Clear | None | None |
| EC-001 | Reject a Gemini request with no configured key without provider fallback. | Clear | None | None |
| EC-002 | Surface Gemini upstream failures and timeouts without false success. | Clear | None | None |

## Acceptance Criteria

| AC ID | Source | Acceptance Criterion |
|---|---|---|
| AC-001 | Analyst | A Gemini model request with configured credentials calls Gemini and returns an Ollama-compatible payload. |
| AC-002 | Analyst | An Ollama model request keeps forwarding to Ollama unchanged. |
| AC-003 | Analyst | A Gemini request without a key returns a configuration error and calls neither provider. |
| AC-004 | Analyst | Gemini streaming is returned as Ollama-compatible NDJSON with a final completion chunk. |
| AC-005 | Analyst | The astrology pipeline passes chart and knowledge context to Gemini when `astrology: true` is set. |
| AC-006 | Analyst | Gemini upstream errors and timeouts return a clear error without key exposure. |
| AC-007 | Analyst | Invalid JWTs are rejected before either provider is called. |
| AC-008 | Analyst | An explicit `astrology: false` skips the astrology pipeline for the configured model and is removed before forwarding to Ollama. |

## Pasted Test Cases

| Test Case ID | Source | Scenario | Steps | Expected Result | Type | Priority | Parse Quality |
|---|---|---|---|---|---|---|---|
| — | — | No test cases were supplied by the user. | — | — | — | — | — |

## AC to Test Case Comparison

| AC ID | Analyst Acceptance Criterion | Matching Test Case ID | Coverage | Notes |
|---|---|---|---|---|
| AC-001 | Gemini request routes and returns normalized response. | TC-001 | Covered | Mock Gemini HTTP response. |
| AC-002 | Ollama behavior remains unchanged. | TC-002 | Covered | Existing forwarding test plus model routing check. |
| AC-003 | Missing Gemini key does not call providers. | TC-003 | Covered | Assert local configuration error and no upstream request. |
| AC-004 | Streaming is normalized. | TC-004 | Covered | Mock Gemini SSE and assert Ollama-compatible NDJSON. |
| AC-005 | Astrology context reaches Gemini. | TC-005 | Covered | Stub Turso and assert prompt content at Gemini transport. |
| AC-006 | Upstream failures/timeouts are surfaced without secrets. | TC-006 | Covered | Assert status/message and no key in response. |
| AC-007 | Authentication remains provider-independent. | TC-007 | Covered | Assert invalid JWT causes no upstream calls. |
| AC-008 | Explicit astrology false skips pipeline and is stripped before Ollama. | TC-008 | Covered | Assert pipeline is not called and upstream body has no `astrology` field. |

## QA Traceability Matrix

| Requirement ID | AC ID | Test Case ID | Test Type | Priority | Coverage |
|---|---|---|---|---|---|
| FR-001 | AC-001, AC-002 | TC-001, TC-002 | Unit/API | High | Verified |
| FR-002 | AC-005 | TC-005 | Unit/API | High | Verified |
| FR-003 | AC-001, AC-002 | TC-001, TC-002 | Unit/API | High | Verified |
| FR-004 | AC-004 | TC-004 | Unit/API | High | Verified |
| FR-005 | AC-001, AC-003 | TC-001, TC-003 | Unit/API | High | Verified |
| FR-006 | AC-008 | TC-008 | Unit/API | High | Verified |
| NFR-001 | AC-007 | TC-007 | Unit/API | High | Verified |
| NFR-002 | AC-006 | TC-006 | Unit/API | High | Verified |
| EC-001 | AC-003 | TC-003 | Unit/API | High | Verified |
| EC-002 | AC-006 | TC-006 | Unit/API | High | Verified |

## Planned Test Cases

| Test Case ID | Scenario | Steps | Expected Result | Type | Priority |
|---|---|---|---|---|---|
| TC-001 | Gemini non-streaming request | Send authenticated `POST /api/generate` with `model: gemini-...`; mock Gemini API. | Gemini called; response contains Ollama-compatible `model`, `response`, and `done` fields. | Unit/API | High |
| TC-002 | Ollama request regression | Send an Ollama model request using existing API. | Request reaches Ollama unchanged; Gemini is not called. | Unit/API | High |
| TC-003 | Missing Gemini key | Send a Gemini model request without `GEMINI_API_KEY`. | Clear configuration error; neither provider is called. | Unit/API | High |
| TC-004 | Gemini streaming | Send `stream: true`; mock Gemini SSE chunks and completion. | Ollama-compatible NDJSON chunks and final completion are returned. | Unit/API | High |
| TC-005 | Astrology through Gemini | Send a Gemini request with `astrology: true` and chart data; stub Turso and mock Gemini. | Prompt contains chart and knowledge context; normalized Gemini response returned. | Unit/API | High |
| TC-006 | Gemini timeout/error | Mock timeout and non-success response. | Appropriate upstream error; no API key in response. | Unit/API | High |
| TC-007 | Invalid JWT on Gemini model | Send Gemini model request with invalid token. | 401; Gemini and Ollama are not called. | Unit/API | High |
| TC-008 | Pre-enriched prompt with configured astrology model | Send `astrology: false` and a configured astrology model. | Astrology pipeline is skipped; proxy removes the flag before Ollama forwarding. | Unit/API | High |

## Extra or Conflicting Test Cases

| Test Case ID | Issue Type | Reason | Required Action |
|---|---|---|---|
| — | — | None | — |

## Edge Cases and Negative Tests

| ID | Scenario | Expected Handling | Covered By |
|---|---|---|---|
| EC-001 | Gemini prefix but no API key | Return a clear configuration error; no Ollama fallback. | TC-003 |
| EC-002 | Gemini API timeout or non-success response | Return an upstream error without credential exposure. | TC-006 |
| EC-003 | Invalid JWT on a Gemini request | Reject before provider access. | TC-007 |
| EC-004 | Streaming completion / upstream stream ends | Emit a final completion chunk or a clear stream error. | TC-004 |

## Open Questions

- None. Provider selection, astrology coverage, and streaming behavior were
  explicitly selected by the user.

## Implementation Readiness

- Ready for architecture: Yes
- Ready for implementation: Yes
- Blocking gaps: None.

## Verification Results

- Command: `.venv/bin/pytest tests`
- Result: 23 passed.
- Note: pytest reports deprecation warnings from the installed
  `pytest-asyncio` version; there are no test failures.
