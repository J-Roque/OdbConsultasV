# Scrapling en OBD Consultas

[Scrapling](https://github.com/D4Vinci/Scrapling) es el motor de scraping que usa
este proyecto para los portales con JavaScript y protecciones anti-bot. Se usa
como **dependencia** (`scrapling[fetchers,rag]`), no se copia su codigo.

Licencia de Scrapling: BSD-3-Clause. Es compatible con este proyecto; al
actualizar, revisar su changelog por cambios de API.

## Por que una dependencia y no una copia

Copiar el paquete completo traeria decenas de archivos, sus dependencias y la
obligacion de mantener el bypass de Cloudflare a mano. La API de Scrapling ya
resuelve eso y se actualiza. Todo su uso esta concentrado en
`src/obd_consultas/infrastructure/scrapling_engine.py`; si una version cambia,
solo se ajusta ese archivo.

## Que se tomo de Scrapling

| Capacidad | Uso en OBD Consultas |
|---|---|
| `StealthySession` / `StealthyFetcher` | Navegador Chromium parcheado que resuelve Cloudflare Turnstile/Interstitial y ejecuta JavaScript |
| `Fetcher` | HTTP rapido con huella TLS de Chrome (`curl_cffi`), para portales sin JavaScript |
| `Selector` | CSS, XPath, pseudoelementos (`::text`, `::attr(href)`), texto, atributos y busqueda por regex |
| Selectores adaptativos | Opcion `adaptive` en `parse_html` para reencontrar elementos si el portal cambia |
| `ProxyRotator` | Rotacion de proxies por variable de entorno |
| Sesiones y reintentos | `retries`, `timeout`, cookies y perfil de navegador opcional |
| `FetcherSession` | `http_session` conserva cookies para formularios ASP.NET/PHP |
| Markdown limpio | `to_markdown` reutiliza la limpieza de Scrapling y `markdownify` |
| Bloqueo de anuncios | Activo por defecto en el navegador sigiloso |

Lo que **no** se trajo, porque una consulta por placa no lo necesita: spiders,
pause/resume de crawls, AutoThrottle, robots.txt, plantillas Shopify/Sitemap,
MCP server y shell interactivo. Si mas adelante se hace un crawl de catalogo,
se pueden agregar sin rehacer los conectores.

## Archivos

```text
infrastructure/scrapling_engine.py  Sesion sigilosa, HTTP, proxies y parser
infrastructure/extraction.py        Reglas reutilizables (Field, extract_rows, tabla, Markdown)
infrastructure/soat_stealth.py      SOAT desatendido: conduce el formulario real y lee API o DOM
infrastructure/sunarp_stealth.py    SUNARP desatendido: formulario Angular, API o tarjeta visible
infrastructure/mtc_stealth.py       MTC desatendido: sesion HTTP, captcha con OCR local
```

La API HTTP (`api/app.py`) solo abre navegadores a traves de los trabajos
`/v1/queries/stealth` y `/v1/queries/assisted`. El modo sigiloso es una entrada
de CLI, igual que el modo asistido. MTC desatendido usa `FetcherSession` de
Scrapling para conservar la cookie del captcha y resuelve la imagen con OCR
local. El modo asistido de MTC usa Playwright visible como respaldo.

## Uso

Instalar navegadores una vez:

```powershell
uv sync --extra dev
uv run obd-consultas install-browsers
```

SOAT desatendido:

```powershell
uv run obd-consultas query soat ABC123 --stealth --timeout 180
uv run obd-consultas query soat ABC123 --stealth --show-browser
uv run obd-consultas query soat ABC123 --stealth --real-chrome
```

SUNARP desatendido:

```powershell
uv run obd-consultas query sunarp ABC123 --stealth --timeout 180
uv run obd-consultas query sunarp ABC123 --stealth --show-browser
```

SUNARP devuelve una imagen PNG de la tarjeta TIVE; el conector la valida y la
entrega en `data.tarjeta`. Ver [SUNARP.md](SUNARP.md).

MTC desatendido (captcha leido con OCR local):

```powershell
uv run obd-consultas query mtc ABC123 --stealth --timeout 180
```

Extraer una pagina para investigar un portal nuevo:

```powershell
# HTTP con huella de Chrome
uv run obd-consultas extract "https://ejemplo.gob.pe/consulta" portal.html

# Navegador sigiloso, esperando el resultado
uv run obd-consultas extract "https://ejemplo.gob.pe/consulta" portal.md `
  --stealth --wait-selector "#resultado" --main-content

# Solo una parte y en texto
uv run obd-consultas extract "https://ejemplo.gob.pe/consulta" salida.txt `
  --stealth --css "table#resultado"
```

Formatos: `.md` (Markdown), `.txt` (texto) o `.html`. Se pueden forzar con
`--format`. Sin `--output`, imprime en consola. El archivo destino no se
reemplaza salvo con `--force`.

## Variables de entorno

| Variable | Efecto |
|---|---|
| `OBD_PROXY_URL` | Proxy unico, por ejemplo `http://usuario:clave@host:8080` |
| `OBD_PROXY_ROTATION` | Lista separada por comas de proxies a rotar |

Los flags `--proxy` y `--profile` tienen prioridad en la CLI. `--profile DIR`
reutiliza cookies y almacenamiento del navegador; es opcional y esta desactivado
por defecto. Sin esa opcion no se guardan cookies ni sesiones.

## Agregar un conector nuevo

El extractor permite describir filas sin escribir CSS repetido:

```python
from obd_consultas.infrastructure.extraction import Field, extract_rows

rows = extract_rows(
    html,
    "table#resultado tr.fila",
    (
        Field("placa", "td:nth-child(1)::text"),
        Field("estado", "td:nth-child(2)::text"),
        Field("ficha", "a", mode="url"),
        Field("fecha", "td:nth-child(3)::text", pattern=r"(\d{2}/\d{2}/\d{4})"),
    ),
    url="https://portal.gob.pe/consulta",
)
```

Si el portal cambia, se puede activar `parse_html(..., adaptive=True)` y usar
`identifier` en el selector para intentar reubicar el elemento. No se debe
publicar un conector sin haber visto el formulario y el resultado reales.

## Limites y seguridad

- Scrapling resuelve el reto de Cloudflare, pero no garantiza que un portal
  siempre lo permita. Si no hay resultado, se devuelve `requires_interaction` o
  `unavailable`; nunca se inventa un `not_found`.
- No se extraen, reutilizan ni falsifican tokens de Turnstile. Se conduce el
  formulario oficial dentro del navegador.
- No se registran placas, propietarios, cookies ni cuerpos de respuesta en logs.
  Los logs informativos de Scrapling se bajan a `WARNING`.
- Un proxy mal configurado o un navegador sin instalar se reporta como
  `unavailable` con una instruccion concreta.
- El modo sigiloso consume mas memoria y tiempo que el HTTP directo. Usar HTTP
  cuando el portal no exige JavaScript.
- SUNARP entrega la tarjeta TIVE como imagen, no como campos JSON. El conector no
  hace OCR: expone la imagen oficial y valida que la placa de las sedes coincida.
