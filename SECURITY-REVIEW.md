# Security Review

## Scope

Review of the FastAPI backend before Internet exposure, with emphasis on authentication,
transport security, browser execution, personal data, and local query jobs.

## Findings

| # | Severity | File | Lines | Vulnerability | Confidence |
|---|----------|------|-------|---------------|------------|
| 1 | 🟠 HIGH | src/obd_consultas/api/app.py | 90 | Authentication can fail open when `OBD_API_TOKEN` is absent or empty | 9/10 |
| 2 | 🟡 MEDIUM | src/obd_consultas/cli.py | 265 | Exposed HTTP server does not configure TLS for credentials and vehicle data | 10/10 |

## 1. Missing authentication fail-open behavior

The token dependency only rejects requests when `OBD_API_TOKEN` contains a value. If the
variable is absent or empty, protected `/v1/*` routes accept requests without validating
`X-OBD-Token`.

The LAN check in the CLI is not enough, because the FastAPI application can be started
through another Uvicorn invocation or ASGI process without that CLI guard.

### Recommended fix

- Define a startup configuration that records whether the application is bound to
  loopback or an external address.
- Fail closed for external binding when `OBD_API_TOKEN` is absent or empty.
- Require authentication for all `/v1/*` routes even when `create_app()` is used directly.
- Optionally require a separate API token for every environment.

## 2. No TLS when exposed outside loopback

Uvicorn can be started with `--host 0.0.0.0`, but the CLI does not configure an SSL key
or certificate. The token, plate numbers, query results, and personal data can therefore
be intercepted on the network.

### Recommended fix

- Use HTTPS through a reverse proxy such as Caddy or IIS, with valid certificates.
- Or configure Uvicorn with `ssl_keyfile` and `ssl_certfile`.
- Never transmit `X-OBD-Token` over unencrypted HTTP outside a trusted local network.

## Minimum before Internet deployment

1. Replace fail-open authentication with fail-closed authentication.
2. Enable HTTPS or place the application behind a TLS reverse proxy.
3. Add request rate limits and limits for concurrent browser queries.
4. Restrict CORS and allowed origins.
5. Add structured security logging without plate numbers or response bodies.
6. Store and transmit only the fields required by the application.
7. Avoid storing downloaded TIVE images or other personal data unless explicitly required.

## Deployment guidance

The backend is suitable for a trusted LAN only after authentication is enabled. It should
not be exposed directly to the public Internet in its current configuration.
