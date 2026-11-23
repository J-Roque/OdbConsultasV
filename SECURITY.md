# Seguridad

Politica de seguridad de OBD Consultas: manejo de secretos, datos personales y
proteccion de la API. Sustituye a la revision puntual `SECURITY-REVIEW.md`; sus
hallazgos estan resueltos en la seccion [Historial de hallazgos](#historial-de-hallazgos).

## Reportar un problema

Proyecto personal. Si encuentras una vulnerabilidad, **no abras un issue
publico**: usa *Security > Report a vulnerability* (aviso privado) en GitHub.

## 1. Secretos

**Regla:** ningun secreto en el codigo, en git, en issues, PRs, capturas ni logs.

| Donde | Que va |
|---|---|
| `.env` (ignorado por git) | Valores reales: `OBD_API_TOKEN`, `OBD_PROXY_URL` |
| `.env.example` (versionado) | Solo nombres de variables y valores vacios o de ejemplo |
| Secrets de GitHub Actions | Cualquier secreto que necesite CI (hoy ninguno) |
| APK | Token en `EncryptedSharedPreferences`/Keystore, nunca en el codigo fuente |

- Genera tokens con `uv run obd-consultas token` (48 bytes aleatorios). Minimo 32 caracteres.
- Credenciales de proxy solo en `OBD_PROXY_URL`: `--proxy usuario:clave@...` queda
  en el historial de la consola (la CLI lo advierte).
- Si un secreto llego a un commit, **considerarlo comprometido**: rotarlo primero y
  despues limpiar el historial (`git filter-repo`). Borrarlo en un commit nuevo no basta.

### Defensas automaticas

1. **`.gitignore`**: `.env`, `.env.*`, `*.pem`, `*.key`, `*.pkl`, `*cookies*`,
   `.cache/`, `artifacts/`, `capturas/`, etc.
2. **Hook `pre-commit`** (`.githooks/pre-commit` -> `scripts/check_secrets.py`):
   bloquea archivos prohibidos aunque se use `git add -f`, y patrones de secretos
   (claves privadas, tokens de GitHub/AWS/Google, JWT, URLs con credenciales,
   asignaciones con valor a variables tipo TOKEN, SECRET o PASSWORD). Activalo tras clonar:
   `git config core.hooksPath .githooks`.
3. **CI**: el mismo escaner sobre todo el repo y **gitleaks** sobre el historial
   completo en cada push y PR a `main`/`develop`.

Un falso positivo con datos sinteticos se marca en la misma linea con
`# secret-scan: allow`. No usar `--no-verify`.

## 2. Datos personales

Las fuentes devuelven datos de personas (nombre del propietario en la TIVE,
placas, certificados). Reglas:

- **No persistir resultados.** La API guarda trabajos solo en memoria (max. 100) y
  se pierden al reiniciar. La CLI imprime en consola.
- **Tests y fixtures solo con datos sinteticos.** Nunca placas ni nombres reales.
- **`.cache/` y `artifacts/` son locales**: pueden tener cookies, capturas de la
  tarjeta TIVE y respuestas reales. No se versionan; borralos cuando termines una
  investigacion (`Remove-Item -Recurse .cache\*.json, .cache\*.png, .cache\*.pkl`).
- No pegar respuestas reales en issues, PRs ni documentacion; anonimizar antes.
- La APK debe pedir consentimiento antes de guardar una tarjeta en el dispositivo.

## 3. API

Implementado en `src/obd_consultas/api/security.py`. Detalle en [docs/API.md](docs/API.md#seguridad).

| Control | Estado |
|---|---|
| Token obligatorio, fail-closed (503 sin token valido) | Activo |
| Comparacion en tiempo constante (`hmac.compare_digest`) | Activo |
| Limite de peticiones por IP antes de autenticar (429) | Activo, `OBD_API_RATE_LIMIT` |
| Limite de consultas simultaneas (429) | Activo, `OBD_API_MAX_ACTIVE_JOBS` |
| `/docs` y `/openapi.json` ocultos | Por defecto; `OBD_API_DOCS=1` |
| Consulta asistida (navegador visible) deshabilitada | Por defecto; `OBD_API_ASSISTED=1` |
| `Cache-Control: no-store` y cabeceras defensivas | Activo |
| Sin access log ni cabecera `Server` | Activo |
| TLS | Opcional: `--ssl-certfile/--ssl-keyfile` o proxy inverso |

**Toda ruta nueva bajo `/v1/` debe usar `dependencies=protected`.** El test
`test_every_v1_route_requires_token` falla si alguna queda sin token.

### Antes de exponer a Internet

La API esta pensada para la PC local o una LAN de confianza. Para Internet falta:

1. HTTPS obligatorio (proxy inverso como Caddy con certificado valido).
2. Un token por cliente, con rotacion y revocacion (hoy hay un token compartido).
3. Limite de peticiones persistente o en el proxy (el actual vive en memoria y es por proceso).
4. Logs de seguridad estructurados sin placas ni respuestas.

## Historial de hallazgos

| Fecha | Hallazgo | Severidad | Estado |
|---|---|---|---|
| 2026-11-23 | Autenticacion fail-open sin `OBD_API_TOKEN` | Alta | Corregido: fail-closed en la app y en `serve` |
| 2026-11-23 | Token comparado con `!=` | Baja | Corregido: `hmac.compare_digest` |
| 2026-11-23 | Sin limite de peticiones ni de hilos de consulta | Media | Corregido: 429 por IP y por trabajos activos |
| 2026-11-23 | `/docs` y `/openapi.json` publicos | Baja | Corregido: ocultos por defecto |
| 2026-11-23 | Consulta asistida remota abre navegador en la PC | Media | Corregido: deshabilitada por defecto |
| 2026-11-23 | HTTP sin TLS al exponer | Media | Mitigado: opcion `--ssl-*` y aviso; HTTPS pendiente para Internet |
