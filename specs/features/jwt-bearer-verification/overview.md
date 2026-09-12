# JWT Bearer Verification

## Goal

Require every proxied request to present a valid, client-provided JWT before
the request can reach Ollama.

## Scope

- Verify the `Authorization: Bearer <JWT>` credential at the existing proxy
  authorization boundary.
- Use `API_TOKEN` as the shared HS256 signing secret.
- Require and validate the JWT `exp` claim.
- Enforce expiry immediately at `exp` (zero clock-skew grace period).
- Remove support for the existing raw `Authorization: Bearer <API_TOKEN>`
  credential.

## Out of Scope

- Issuing JWTs.
- Persistent user, session, or token-revocation storage.
- Issuer (`iss`), audience (`aud`), or custom-claim validation.
- Database and frontend changes.

## Acceptance Criteria

1. Given a request with an HS256 JWT signed using `API_TOKEN` and a future
   `exp` claim, when it reaches any proxied route, then the proxy forwards it
   to the upstream service.
2. Given a JWT with a modified or invalid signature, when it reaches any
   proxied route, then the proxy returns HTTP 401 and does not call upstream.
3. Given an expired JWT or a JWT without `exp`, when it reaches any proxied
   route, then the proxy returns HTTP 401 and does not call upstream.
4. Given a JWT using an algorithm other than HS256, when it reaches any
   proxied route, then the proxy returns HTTP 401 and does not call upstream.
5. Given the previous raw `Authorization: Bearer <API_TOKEN>` credential,
   when it reaches any proxied route, then the proxy returns HTTP 401 and does
   not call upstream.
6. Given a malformed or absent authorization credential, when it reaches any
   proxied route, then the proxy returns HTTP 401 with the existing Bearer
   challenge and does not call upstream.

## Affected Areas

- `src/ollama_proxy/app.py`: request authentication.
- `pyproject.toml` and `requirements.txt`: JWT verification dependency, if
  needed.
- `tests/test_proxy.py`: authorization tests.

## User Decisions

- `API_TOKEN` is the HS256 signing key.
- `API_TOKEN` must be at least 32 bytes; startup fails otherwise.
- Client-provided tokens are verified only; this service does not issue JWTs.
- `exp` is mandatory.
- Raw API-token authentication is removed.
