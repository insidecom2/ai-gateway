# Requirements QA Alignment: Astrology Answer Quality

## Gate Status

- Status: Approved
- Reviewer Notes: Requirements are observable and mapped to planned unit cases for both endpoints and providers. Explicit user approval of this document is required before the workflow continues.

## Requirement Quality Review

| ID | Requirement | Quality | Issue | Resolution Needed |
|----|-------------|---------|-------|-------------------|
| FR-001 | Astrology-enabled answers explain the interpretation in accessible language and ground it in retrieved Thai astrology knowledge. | Testable | Provider output is probabilistic; unit tests can verify retrieved context and prompt instructions. | None |
| FR-002 | Client-visible astrology answers contain no citations, source identifiers, metadata, or natural-language attribution. | Testable | Tests verify source metadata is omitted from the generation prompt, the prompt disallows attribution, and the response shape adds no source fields. | None |
| FR-003 | Non-astrology response behavior remains unchanged. | Testable | Existing bypass behavior has unit coverage. | None |
| FR-004 | Both generate/chat and Ollama/Gemini astrology paths follow the same requirements. | Testable | Provider request capture can verify prompt/context across each path. | None |
| NFR-001 | Preserve existing Ollama-compatible response shape and streaming support. | Testable | Existing endpoint response and streaming formats can be regression-tested. | None |
| FR-005 | Translate English/Chinese input into Thai before RAG retrieval and analysis, then translate the answer back to the detected input language without adding an API language field. | Testable | Tests can verify translated query passed to RAG and response-language instruction for both providers. | None |
| EC-006 | Fall back to Thai when the latest user message is too short or mixed to identify a response language reliably. | Testable | Test ambiguous/short messages and assert the Thai fallback instruction. | None |

## Acceptance Criteria

### Astrology answer quality and source visibility

| AC ID | Source | Acceptance Criterion |
|-------|--------|----------------------|
| AC-001 | Analyst | Given `astrology: true` and retrieved RAG context, when a prompt is built, then it instructs the provider to explain the interpretation in accessible language, ground it in retrieved Thai astrology knowledge, and avoid unsupported claims. |
| AC-002 | Analyst | Given `astrology: true`, when a response is returned to a client, then the prompt does not request citations and the response does not expose source identifiers, metadata, citations, or natural-language source attribution. |
| AC-003 | Analyst | Given astrology is not enabled, then existing response behavior is unchanged. |
| AC-004 | Analyst | Given `/api/generate` or `/api/chat` is called with astrology enabled and either Ollama or Gemini selected, then the prompt uses retrieved Thai astrology context, follows the same source visibility instructions, and specifies the detected response language. |
| AC-005 | Analyst | Given an astrology-enabled request uses streaming, when the response is returned, then the existing endpoint-compatible streaming format is preserved and the prompt does not request source references. |
| AC-006 | Analyst | Given an astrology-enabled request in English or Chinese, then the question is translated to Thai before RAG retrieval and analysis, and the provider is explicitly instructed to return the analyzed answer in the detected input language without a new API field. |
| AC-007 | Analyst | Given an astrology-enabled request whose latest user message is too short or mixed to identify a response language reliably, then the answer uses Thai. |

## Pasted Test Cases

| Test Case ID | Source | Scenario | Steps | Expected Result | Type | Priority | Parse Quality |
|--------------|--------|----------|-------|-----------------|------|----------|---------------|
| — | — | No test cases supplied by user. | — | — | — | — | — |

## AC to Test Case Comparison

| AC ID | Analyst Acceptance Criterion | Matching Test Case ID | Coverage | Notes |
|-------|------------------------------|-----------------------|----------|-------|
| AC-001 | Accessible explanation grounded in Thai astrology RAG context. | TC-001–TC-004 | Covered | Verify prompt instructions and retrieved context for Ollama/Gemini and generate/chat. |
| AC-002 | No source details or attribution in client-visible response. | TC-001–TC-004 | Covered | Verify no citation request or source metadata is added to client response. |
| AC-003 | Non-astrology requests unchanged. | TC-005 | Covered | Existing regression checks the astrology bypass and response pass-through. |
| AC-004 | Same behavior and response-language instruction across endpoints/providers. | TC-001–TC-004, TC-007–TC-008 | Covered | Cases cover Ollama/Gemini, generate/chat, and detected target language. |
| AC-005 | Preserve streaming shape and do not request citations. | TC-006 | Covered | Existing streaming format cases remain; prompt instructions can be inspected in astrology path. |
| AC-006 | Translate English/Chinese to Thai before RAG, then explicitly request the detected input language in the provider prompt. | TC-007–TC-008 | Covered | Verify translated query and output-language instruction for English and Chinese input. |
| AC-007 | Use Thai when input language cannot be confidently identified. | TC-009 | Covered | Verify fallback behavior for short or mixed-language text. |

## QA Traceability Matrix

| Requirement ID | AC ID | Test Case ID | Test Type | Priority | Coverage |
|----------------|-------|--------------|-----------|----------|----------|
| FR-001 | AC-001 | TC-001–TC-004 | Unit | High | Covered |
| FR-002 | AC-002 | TC-001–TC-004 | Unit | High | Covered |
| FR-003 | AC-003 | TC-005 | Unit | Medium | Covered |
| FR-004 | AC-004 | TC-001–TC-004 | Unit | High | Covered |
| NFR-001 | AC-005 | TC-006 | Unit | Medium | Covered |
| FR-005 | AC-006 | TC-007–TC-008 | Unit | High | Covered |
| EC-006 | AC-007 | TC-009 | Unit | Medium | Covered |

## Planned Test Cases

| Test Case ID | Scenario | Steps | Expected Result | Type | Priority |
|--------------|----------|-------|-----------------|------|----------|
| TC-001 | Astrology Ollama generate prompt | Send `/api/generate` with `astrology: true` and English input; capture the provider request. | Prompt includes Thai-translated input and retrieved Thai astrology content, requests an accessible English answer, and contains no source identifiers or citation request. | Unit | High |
| TC-002 | Astrology Ollama chat prompt | Send `/api/chat` with `astrology: true` and Chinese input; capture Ollama messages. | Prompt includes Thai-translated input and retrieved Thai astrology content, requests an accessible Chinese answer, and contains no source identifiers or attribution request. | Unit | High |
| TC-003 | Astrology Gemini generate prompt | Send `/api/generate` with a Gemini model, `astrology: true`, and English input; capture Gemini request. | System instruction and prompt explicitly request an accessible English answer, preserve RAG grounding, and omit source identifiers and citations. | Unit | High |
| TC-004 | Astrology Gemini chat prompt | Send `/api/chat` with a Gemini model, `astrology: true`, and Chinese input; capture Gemini request. | System instruction and prompt explicitly request an accessible Chinese answer, preserve RAG grounding, and omit source identifiers and attribution. | Unit | High |
| TC-005 | Non-astrology regression | Send a request without `astrology: true`. | Astrology pipeline is bypassed and upstream response behavior remains unchanged. | Unit | Medium |
| TC-006 | Streaming compatibility | Exercise astrology-enabled streaming in the applicable endpoint/provider paths. | Existing Ollama-compatible streaming format is preserved and the prompt does not request citations. | Unit | Medium |
| TC-007 | English astrology request translation | Send an English question to an astrology-enabled request; capture the Thai query used for RAG lookup and final provider prompt. | RAG lookup uses Thai translation; final Ollama/Gemini prompt explicitly requests accessible English, no citations, and use of Thai RAG knowledge. | Unit | High |
| TC-008 | Chinese astrology request translation | Send a Chinese question to an astrology-enabled request; capture the Thai query used for RAG lookup and final provider prompt. | RAG lookup uses Thai translation; final Ollama/Gemini prompt explicitly requests accessible Chinese in the detected script, no citations, and use of Thai RAG knowledge. | Unit | High |
| TC-009 | Ambiguous input language fallback | Send a short or mixed-language latest user message that cannot reliably identify the intended response language. | The pipeline uses Thai as the response-language fallback and does not require an API language field. | Unit | Medium |

## Extra or Conflicting Test Cases

| Test Case ID | Issue Type | Reason | Required Action |
|--------------|------------|--------|-----------------|
| — | — | No user-provided test cases to compare. | — |

## Edge Cases and Negative Tests

| ID | Scenario | Expected Handling | Covered By |
|----|----------|-------------------|------------|
| EC-001 | Retrieved context includes `document_key`, `chunk_key`, and `source_locator`. | Keep RAG content for internal grounding, but omit source metadata from the provider prompt and do not ask it to show attribution. | TC-001–TC-004 |
| EC-002 | No birth chart data is provided. | Use only the question and retrieved context; do not imply a chart was calculated. | Existing input/context tests; extend prompt test if needed. |
| EC-003 | Relevant RAG context is sparse or absent. | Avoid unsupported Thai astrology claims and do not invent citations. | TC-001–TC-004 prompt assertions |
| EC-004 | Astrology is not enabled. | Preserve non-astrology routing and output. | TC-005 |
| EC-005 | Streaming is enabled. | Preserve endpoint-compatible response format and no-citation prompt instructions. | TC-006 |
| EC-006 | Latest user message is short or mixed-language. | Use Thai as the response-language fallback. | TC-009 |

## Open Questions

- None.

## Implementation Readiness

- Ready for architecture: Yes, after explicit user approval of this updated document.
- Ready for implementation: Yes, after approval and completion of remaining workflow gates.
- Blocking gaps:
  - User approval of this updated requirements QA alignment is required before continuing.
