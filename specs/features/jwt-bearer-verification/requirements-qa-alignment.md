# Requirements QA Alignment: JWT Bearer Verification

## Gate Status

- Status: Approved
- Reviewer Notes: The contract is observable and testable. No supplied tests
  conflict with it.

## Requirement Quality Review

| ID | Requirement | Quality | Issue | Resolution Needed |
|---|---|---|---|---|
| FR-001 | Verify Bearer JWTs using `API_TOKEN` and HS256. | Clear | None | None |
| FR-002 | Require a valid future `exp` claim with zero clock-skew grace. | Clear | None | None |
| FR-003 | Reject raw API tokens and invalid credentials. | Clear | None | None |
| NFR-001 | Do not forward rejected requests upstream. | Clear | None | None |
| NFR-002 | Reject HS256 signing keys shorter than 32 bytes at startup. | Clear | None | None |

## Acceptance Criteria

| AC ID | Source | Acceptance Criterion |
|---|---|---|
| AC-001 | Analyst | A valid HS256 JWT with future `exp` is forwarded. |
| AC-002 | Analyst | Invalid signatures are rejected with 401 without upstream access. |
| AC-003 | Analyst | Expired and no-`exp` JWTs are rejected with 401 without upstream access. |
| AC-004 | Analyst | Non-HS256 JWTs are rejected with 401 without upstream access. |
| AC-005 | Analyst | Legacy raw API tokens are rejected with 401 without upstream access. |
| AC-006 | Analyst | Missing or malformed credentials are rejected with the existing Bearer challenge. |

## QA Traceability Matrix

| Requirement ID | AC ID | Test Case ID | Test Type | Priority | Coverage |
|---|---|---|---|---|---|
| FR-001 | AC-001 | TC-001 | Unit/API | High | Planned |
| FR-001 | AC-002, AC-004 | TC-002, TC-004 | Unit/API | High | Planned |
| FR-002 | AC-003 | TC-003 | Unit/API | High | Planned |
| FR-003 | AC-005, AC-006 | TC-005, TC-006 | Unit/API | High | Planned |
| NFR-001 | AC-002–AC-006 | TC-002–TC-006 | Unit/API | High | Planned |

## Planned Test Cases

| Test Case ID | Scenario | Expected Result | Type | Priority |
|---|---|---|---|---|
| TC-001 | Valid, signed, future-expiry HS256 JWT | Request reaches upstream. | Unit/API | High |
| TC-002 | JWT with invalid signature | 401; upstream not called. | Unit/API | High |
| TC-003 | Expired or missing-`exp` JWT | 401; upstream not called. | Unit/API | High |
| TC-004 | Non-HS256 JWT | 401; upstream not called. | Unit/API | High |
| TC-005 | Raw `API_TOKEN` bearer credential | 401; upstream not called. | Unit/API | High |
| TC-006 | Missing or malformed authorization credential | 401 and `WWW-Authenticate: Bearer`; upstream not called. | Unit/API | High |

## Edge Cases and Negative Tests

| ID | Scenario | Expected Handling | Covered By |
|---|---|---|---|
| EC-001 | JWT parse failure | Generic 401 response; no upstream call. | TC-006 |
| EC-002 | Algorithm-confusion attempt | Only HS256 is allowed. | TC-004 |
| EC-003 | Secret is unset | Existing startup validation remains effective. | Existing lifespan test/manual check |

## Open Questions

- None.

## Implementation Readiness

- Ready for architecture: Yes
- Ready for implementation: Yes
- Blocking gaps: None.
