# Astrology Answer Quality

## Goal

When a request enables the existing astrology pipeline, return an answer with enough clear explanation for a person to understand the interpretation. Ground the analysis in Thai astrology knowledge retrieved through RAG, keep source references internal, and support English and Chinese client input.

## Scope

- Applies to the astrology-enabled generation and chat flows (`astrology: true`) for Ollama and Gemini.
- The existing request field is `astrology`; `use_astrology` is not present in the current API implementation.
- Improve the instructions used to generate astrology answers.
- Keep retrieved Thai astrology knowledge available internally through RAG to ground the answer.
- Do not include citations, source identifiers, metadata, or natural-language attribution in the client-visible answer.
- Support client requests written in English and Chinese.
- Translate the incoming question to Thai before RAG retrieval and analysis.
- Detect the language from the latest user message; when sending the analysis prompt to the selected provider, explicitly request the final answer in that language and translate the Thai analysis into it without requiring a new API field.
- If the latest message is too short or mixed for reliable language detection, use Thai as the response-language fallback.
- Non-astrology requests remain unchanged.

## Acceptance Criteria

- AC-001: Given `astrology: true` and retrieved RAG context, then the analysis is grounded in the retrieved Thai astrology knowledge and the client-visible answer clearly explains the interpretation in language a general user can understand.
- AC-002: Given `astrology: true`, when a response is returned to a client, then it contains no citation, source identifier, metadata, or natural-language source attribution.
- AC-003: Given astrology is not enabled, then existing response behavior is unchanged.
- AC-004: Given either Ollama or Gemini handles an astrology-enabled request, then answer grounding and source visibility follow the same requirements for both providers and both generate/chat endpoints.
- AC-005: The response retains the existing Ollama-compatible response shape and streaming behavior.
- AC-006: Given an astrology-enabled request in English or Chinese, then the question is translated to Thai before RAG retrieval and analysis, and the analyzed answer is translated back to the detected input language.
- AC-007: Given an astrology-enabled request whose latest user message is too short or mixed to identify a response language reliably, then the answer uses Thai, and no new request field is required for language selection.

## API Candidates

- `POST /api/generate`: existing `astrology` request flag and `response` output.
- `POST /api/chat`: existing `astrology` request flag and `message.content` output.

No new API fields are proposed.

## Event Flow

1. Proxy detects `astrology: true` and extracts the latest user question.
2. For English or Chinese input, translate the question to Thai before retrieving matching Thai astrology context through RAG.
3. Compute the chart when birth data is provided and analyze the Thai question with the retrieved context. Source identifiers stay internal and are not requested in the client-visible answer.
4. Send the Thai analysis context to Ollama or Gemini with an explicit instruction to produce the final answer in the detected response language.
5. Proxy returns the translated answer using the existing endpoint response shape.

## Edge Cases

- Missing chart data: explain only what the question and retrieved context support; do not imply a chart was calculated.
- Missing relevant context: avoid unsupported claims and do not invent astrology facts or citations.
- Streaming responses: source visibility rules apply to the client-visible output.
- Provider differences: translation, analysis, and source visibility behavior must be consistent across Ollama and Gemini.
- If the latest user message is too short or mixed for reliable language detection, use Thai as the fallback response language.
- Non-astrology requests: do not change their output.

## Resolved Decisions

- User decision: omit all citations and source attribution from client-visible answers, including natural-language attribution.
- User clarification: continue grounding the analysis in Thai astrology knowledge retrieved through RAG; source references remain internal.
- User decision: translate incoming English/Chinese questions to Thai for RAG retrieval and analysis, then detect the language from the latest user message and instruct the selected provider to translate the analysis into that language; no language field is needed. Use Thai when the message does not identify a language reliably.

## Open Questions

- None.

## Affected Layers

- Backend: `src/ollama_proxy/astrology.py` prompt construction and tests.
- Database: no schema or persistence changes expected.
- Frontend: no changes expected.
