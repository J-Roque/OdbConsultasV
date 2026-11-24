# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
[versionado semantico](https://semver.org/lang/es/).

## [Sin publicar]

### Agregado
- Fuente `sat` (SAT de Lima, orden de captura) en modo stealth: sesion HTTP,
  captcha de imagen con OCR local y reintentos. Experimental (`implemented=false`):
  el parser es provisional hasta validarlo con una respuesta real.
- SUTRAN funciona en modo stealth: el conector pulsa Consultar y deja que el
  sitio obtenga su token de Turnstile (antes lo esperaba antes de pulsar y nunca
  llegaba). Validado con consultas reales sin documentos; sigue experimental
  hasta ver un caso con documentos.
- `OBD_DEBUG_DIR` guarda el HTML crudo de la respuesta del SAT para ajustar el parser.
- `docs/COBERTURA-APP.md`: fuentes que necesita la app ObdScanner y diferencias de contrato.

## [0.2.0] - 2026-11-23

### Seguridad
- La API exige `OBD_API_TOKEN` siempre (minimo 32 caracteres); sin token valido
  `/v1/*` responde 503 en vez de quedar abierta.
- Token comparado en tiempo constante.
- Limite de peticiones por IP (`OBD_API_RATE_LIMIT`) y de consultas simultaneas
  (`OBD_API_MAX_ACTIVE_JOBS`); responden 429 con `Retry-After`.
- `/docs`, `/redoc` y `/openapi.json` ocultos salvo `OBD_API_DOCS=1`.
- `POST /v1/queries/assisted` deshabilitado salvo `OBD_API_ASSISTED=1`.
- Cabeceras `Cache-Control: no-store`, `nosniff`, `no-referrer`; sin cabecera `Server`.
- Escaner de secretos en hook `pre-commit` y en CI (mas gitleaks).

### Agregado
- `obd-consultas token` genera un token aleatorio.
- `serve` lee `.env` (`--env-file`) y acepta `--ssl-certfile`/`--ssl-keyfile`.
- `.env.example`, `.gitattributes`, hooks en `.githooks/`, CI, plantilla de PR y Dependabot.
- `SECURITY.md`, `CHANGELOG.md` y Git Flow detallado en `CONTRIBUTING.md`.

### Cambiado
- SUTRAN marcado como experimental (`implemented=false`): el portal exige un
  token Turnstile que aun no se obtiene de forma desatendida.
- **Incompatible:** clientes de la API deben enviar `X-OBD-Token` tambien en loopback.

### Refactor
- `QueryService.run(source, plate, mode)` es la unica puerta de consulta; la CLI y la
  API ya no eligen conectores con `if source == ...`.
- Modos registrados en `bootstrap.RUNNERS` por `(fuente, modo)` con import diferido.
- Codigo comun de los conectores en `infrastructure/connector_common.py`
  (antes duplicado en SOAT, SUNARP, SUTRAN y MTC).
- `ruff` y `mypy` configurados en `pyproject.toml` y ejecutados en CI.

### Cambiado (API)
- Contrato tipado de `data` por fuente (`contracts.py`), publicado en `/openapi.json`
  y verificado en tests; `propietarios.valor` de SUNARP documentado como lista.
- `/v1/sources` incluye `modes` por fuente.
- Fuente no admitida en un modo: 422 con la lista de fuentes validas.
- `browser` en `/v1/queries/assisted` restringido a `msedge`, `chrome` o `chromium`.
- `create_app()` ya no acepta `stealth_runner`/`assisted_runner`: se inyecta un `QueryService`.

### Eliminado
- `SECURITY-REVIEW.md`, reemplazado por `SECURITY.md`.

## [0.1.0] - 2026-11-23

### Agregado
- Base del proyecto: conectores SOAT, SUNARP (TIVE + OCR), MTC (OCR de captcha)
  y SUTRAN experimental; CLI, API local con trabajos asincronos y documentacion por fuente.
