# OBD Consultas

Backend local en Python para investigar e integrar consultas vehiculares de Peru.
Proyecto independiente de `D:\ObdScanner`, para uso personal.

## Estado real

SOAT tiene parsers JSON/DOM y dos modos de consulta: desatendido con navegador
sigiloso y asistido con ventana visible. El 20/11/2026 el modo desatendido obtuvo
un resultado real del portal y Python normalizo los certificados; los datos no se
guardaron.

SUNARP se implemento el 23/11/2026 en modo desatendido con Scrapling. El portal
entrega una imagen PNG de la tarjeta TIVE; el conector la conserva en
`data.tarjeta` y lee sus campos (propietario, serie, motor, color, marca, modelo,
estado, etc.) con OCR local en `data.vehiculo`, cada uno con su confianza. El
estado de robo llega como `data.alerta_robo`. Ver [SUNARP.md](docs/SUNARP.md).

MTC se implemento el 23/11/2026 en modo **desatendido con OCR local**
(`ddddocr`): abre una sesion HTTP, lee el captcha numerico y reintenta si el
portal lo rechaza. Tambien conserva un modo asistido respaldo con navegador
visible. Ver [MTC.md](docs/MTC.md).

SUTRAN tiene un conector **experimental** (`implemented=false`). Existe consulta
publica por placa en `/consultas/placa/{placa}`, pero la API exige el token
`X-Captcha-Token` de Turnstile. La validacion real no obtuvo ese token y la
consulta devuelve `requires_interaction`; no se publica un resultado no
verificado. Ver [SUTRAN.md](docs/SUTRAN.md).

Para las fuentes configuradas, la API basica (`/v1/queries`) y la CLI sin
`--stealth` ni `--interactive` devuelven `requires_interaction` sin consultar
datos ni abrir ventanas.

## Ojo de implementacion

| Fuente | Dato objetivo | Estado |
|---|---|---|
| APESEG / SOAT | Vigencia y aseguradora | Implementado |
| MTC | Revision tecnica y vigencias CITV | Implementado |
| SUNARP | Propiedad, datos tecnicos y estado de robo | Implementado: imagen TIVE + campos con OCR local |
| SUTRAN | Multas por placa | Por validar: exige token Turnstile; conector experimental |
| ATU | Multas por placa | Por validar (alcance publico y privacidad) |
| SBS | Consulta publica por placa o aseguradora | Por validar |
| AAP | Consulta por placa | Por validar |
| INFOGAS / FISE | Instalacion GNV/GLP por placa | Por validar |
| SAT Lima | Orden de captura y papeletas por placa | Por validar (capturas: prioridad 1) |
| SAT Callao | Papeletas por placa | Por validar |
| SUNARP historial | Transferencias y gravamenes | Por validar |
| SUNAT | Consulta tributaria | Requiere numero de documento |
| PNP / DIROVE | Datos policiales | **Excluido**: datos sensibles y acceso restringido |

Inventario completo, orden sugerido y reglas para agregar fuentes:
[PLAN.md](docs/PLAN.md). Que necesita la app ObdScanner y que falta para
conectarla a este backend: [COBERTURA-APP.md](docs/COBERTURA-APP.md).

Modo desatendido (Scrapling resuelve Cloudflare y ejecuta el formulario oficial):

```powershell
uv run obd-consultas query soat TU_PLACA --stealth --timeout 180
```

Si el portal aun exige una accion manual, se devuelve `requires_interaction`.
Opciones utiles: `--show-browser`, `--real-chrome`, `--profile DIR`, `--proxy URL`.

SUNARP desatendido (entrega la tarjeta TIVE como PNG en base64):

```powershell
uv run obd-consultas query sunarp TU_PLACA --stealth --timeout 180
```

El resultado incluye `sedes`, `alerta_robo`, `plate_verified`, `tarjeta` con la
imagen oficial y `vehiculo` con los campos leidos y su confianza. Si Turnstile no
se resuelve, reintenta con sesiones nuevas hasta tres veces antes de pedir
intervencion. Ver [SUNARP.md](docs/SUNARP.md).

MTC desatendido (OCR local del captcha, sin intervencion):

```powershell
uv run obd-consultas query mtc TU_PLACA --stealth --timeout 180
```

Entrega hasta tres registros de revision tecnica, con estado vigente, fechas ISO
y empresa certificadora. Si el OCR falla tras cinco intentos, devuelve
`requires_interaction` y queda el respaldo `--interactive`. Ver [MTC.md](docs/MTC.md).

El modo asistido sigue disponible como respaldo:

```powershell
uv run obd-consultas query soat TU_PLACA --interactive --timeout 300
```

Se abre un navegador temporal y se completa la placa. Completa la verificacion y pulsa
Consultar en el portal si hace falta. El programa lee el resultado visible completo y
cierra el navegador. El modo asistido no guarda cookies ni tokens en disco. El JSON
normalizado se escribe solo en consola. `--browser chrome` usa Chrome; `--browser
chromium` requiere instalar Chromium con Playwright. Edge es el navegador
predeterminado del modo asistido.

## Preparar

```powershell
cd D:\ObdConsultas
uv sync --extra dev
uv run obd-consultas install-browsers
```

`install-browsers` descarga Chromium para Playwright y Patchright (el navegador
sigiloso). Playwright tambien se puede instalar con `uv run playwright install chromium`.

## CLI

```powershell
uv run obd-consultas sources
uv run obd-consultas inspect soat
uv run obd-consultas inspect sunarp
uv run obd-consultas inspect mtc
uv run obd-consultas inspect soat --list
uv run obd-consultas query soat ABC123
uv run obd-consultas query soat ABC123 --stealth
uv run obd-consultas query sunarp ABC123 --stealth
uv run obd-consultas query mtc ABC123 --stealth
```

El comando `query` devuelve JSON y sale con codigo 1 cuando el resultado no es
`success`. La sintaxis anterior `obd-consultas soat --list` sigue funcionando.
Con `--interactive`, las verificaciones que presente el portal se completan
manualmente en el navegador.

## Extraer una pagina

```powershell
uv run obd-consultas extract "https://ejemplo.gob.pe/consulta" portal.md
uv run obd-consultas extract "https://ejemplo.gob.pe/consulta" portal.md --stealth --wait-selector "#resultado"
uv run obd-consultas extract "https://ejemplo.gob.pe/consulta" salida.txt --stealth --css "table#resultado"
```

Sirve para investigar un portal antes de escribir su conector. Formatos `.md`,
`.txt` y `.html`; tambien `--css`, `--xpath`, `--format`, `--main-content` y
`--force`. Los proxies se configuran con `OBD_PROXY_URL` o `OBD_PROXY_ROTATION`.
Ver [Scrapling](docs/SCRAPLING.md).

## API local

La API exige token **siempre** (tambien en `127.0.0.1`). Configuralo una vez:

```powershell
Copy-Item .env.example .env
uv run obd-consultas token          # pega el valor en OBD_API_TOKEN dentro de .env
uv run obd-consultas serve
```

`serve` lee `.env` (las variables ya definidas en la sesion ganan) y se niega a
arrancar sin un token de al menos 32 caracteres. `/docs` esta desactivado; para
desarrollo define `OBD_API_DOCS=1`. Todas las variables: [.env.example](.env.example).

`POST /v1/queries` solo valida y devuelve `requires_interaction`: no consulta los
portales. Para obtener datos reales desde una APK, usar el puente asincrono:

```powershell
$body = @{ source = 'sunarp'; plate = 'ABC123'; timeout = 180 } | ConvertTo-Json
$headers = @{ 'X-OBD-Token' = $env:OBD_API_TOKEN }
$job = Invoke-RestMethod http://127.0.0.1:8000/v1/queries/stealth -Method Post -Headers $headers -ContentType 'application/json' -Body $body
$job.poll_url                      # /v1/jobs/{job_id}
Invoke-RestMethod "http://127.0.0.1:8000$($job.poll_url)" -Headers $headers
```

Hacer polling hasta que `state` sea `done`; `result` trae el `QueryResult` con
los datos normalizados. MTC usa el mismo `/v1/queries/stealth` con
`source='mtc'` y resuelve el captcha con OCR local; `/v1/queries/assisted` queda
como respaldo con navegador visible (desactivado salvo `OBD_API_ASSISTED=1`). Contrato completo, ejemplo Kotlin y
configuracion para telefono: [API.md](docs/API.md).

Para exponer en LAN (con el token ya en `.env`):

```powershell
uv run obd-consultas serve --host 0.0.0.0
uv run obd-consultas serve --host 0.0.0.0 --ssl-certfile cert.pem --ssl-keyfile key.pem
```

Sin `--ssl-*` la API va por HTTP sin cifrar y `serve` lo advierte: solo en redes
de confianza. Controles de seguridad, limites y reglas de datos:
[SECURITY.md](SECURITY.md). La API nunca abre Playwright Inspector ni espera que
alguien complete un formulario.

## Estructura

```text
src/obd_consultas/
  domain/models.py          Placas, fuentes, estados y contrato de resultado
  application/queries.py   Validacion y ejecucion de consultas
  providers/base.py        Interfaz de los conectores
  providers/catalog.py     Catalogo de fuentes
  providers/soat.py        Parser y conector SOAT
  providers/sunarp.py      Parser y conector SUNARP
  providers/mtc.py         Parser y conector MTC
  providers/sutran.py      Parser experimental de SUTRAN
  infrastructure/soat_browser.py  Consulta asistida con Playwright
  infrastructure/soat_stealth.py  Consulta desatendida con Scrapling
  infrastructure/sunarp_stealth.py  Consulta desatendida de SUNARP
  infrastructure/sunarp_ocr.py  Lectura local de la tarjeta TIVE (RapidOCR)
  infrastructure/mtc_browser.py  Consulta asistida de MTC con captcha humano
  infrastructure/mtc_stealth.py  Consulta desatendida de MTC con OCR local
  infrastructure/sutran_stealth.py  Intento desatendido de SUTRAN (experimental)
  infrastructure/scrapling_engine.py  Sesiones sigilosas, HTTP, proxies y parser
  infrastructure/extraction.py  Reglas de extraccion y Markdown
  providers/pending.py     Respuesta explicita para conectores pendientes
  infrastructure/browser.py  Inspeccion manual con Playwright
  api/app.py               Rutas HTTP y contratos OpenAPI
  api/security.py          Token fail-closed, limite de peticiones y flags
  config.py                Lectura de .env sin dependencias
  cli.py                   Comandos de consola
  bootstrap.py             Ensambla servicio y conectores
  __main__.py              Entrada python -m obd_consultas
tests/                    Pruebas de servicio, API, extraccion y modo sigiloso
scripts/check_secrets.py   Escaner de secretos del hook pre-commit y CI
.githooks/                 Hooks versionados (pre-commit, commit-msg)
.github/                   CI, plantilla de PR y Dependabot
SECURITY.md                Politica de seguridad, secretos y datos personales
CONTRIBUTING.md            Git Flow, convenciones de commits y checklist
CHANGELOG.md               Historial de versiones
docs/PLAN.md               Inventario de fuentes, estados y orden sugerido
docs/COBERTURA-APP.md      Fuentes que necesita la app ObdScanner y diferencias de contrato
docs/SAT.md                Evidencia del portal de capturas del SAT de Lima
docs/ARQUITECTURA.md       Decisiones, flujo y plan de implementacion
docs/API.md                Contrato HTTP, trabajos sigilosos y uso desde APK
docs/SOAT.md               Evidencia y flujo del portal APESEG
docs/SUNARP.md             Evidencia, flujo y contrato del portal SUNARP
docs/MTC.md                Evidencia, OCR local, captcha asistido y contrato MTC
docs/SUTRAN.md             Evidencia y estado experimental del portal SUTRAN
docs/SCRAPLING.md          Motor de scraping, comandos y limites
```

## Verificar

```powershell
uv run --extra dev python -m unittest discover -s tests -v
```

Tras clonar, activa los hooks del repositorio (revisan secretos y el formato
del mensaje de commit). Detalles en [CONTRIBUTING.md](CONTRIBUTING.md):

```powershell
git config core.hooksPath .githooks
```

Consulta [la arquitectura](docs/ARQUITECTURA.md) para agregar el primer conector
y [Scrapling](docs/SCRAPLING.md) para el motor de scraping.

## Importar una captura del navegador

```powershell
uv run obd-consultas import-soat artifacts/soat-B8T117.capture.json --plate B8T117
```

La captura real y el resultado normalizado estan en `artifacts/`. Este comando
procesa un archivo; no hace una consulta nueva. Ver [SOAT.md](docs/SOAT.md).
