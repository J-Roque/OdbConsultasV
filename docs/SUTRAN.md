# SUTRAN: papeletas e infracciones por placa

## Evidencia

Inspeccionado el 23 de noviembre de 2026 en:

- https://digital.sutran.gob.pe/
- https://api.dig.sutran.gob.pe/consultas/placa/{placa}

El portal acepta una placa en el campo `placa` y consulta una API publica en
`https://api.dig.sutran.gob.pe/consultas/placa/{placa}`. La API exige la cabecera
`X-Captcha-Token` que genera el widget Turnstile del formulario oficial; sin ese
token devuelve HTTP 403 `CAPTCHA_INVALID`.

## Estado de la validacion

**Parcial: la consulta por placa funciona en modo desatendido.** El 24/11/2026
dos consultas reales con una placa autorizada devolvieron `not_found` con las
fuentes `RECORD_INFRACCIONES`, `PAPELETAS_CINEMOMETRO` y
`VERIFICACION_DOCUMENTOS` respondiendo `ok`. Aun no se vio una placa **con**
documentos, asi que la forma de `documentos` sigue sin validar y la fuente queda
`implemented=false`.

### Por que fallaba antes

El sitio es una app Angular que pide el token de Turnstile **al pulsar
Consultar**, no al cargar: crea el widget oficial con
`appearance: "interaction-only"` (invisible salvo que Cloudflare pida un clic),
espera su callback hasta 120 s y lo envia en `X-Captcha-Token` junto con
`X-Captcha-Espera-Ms`. La version del 23/11 esperaba el token en
`input[name="cf-turnstile-response"]` **antes** de pulsar, y ese campo nunca se
llena con este flujo.

Ahora el conector completa la placa, pulsa Consultar y observa la respuesta de
la API. No lee, extrae ni fabrica el token: lo obtiene el propio sitio. El
solver de Cloudflare de Scrapling sigue desactivado (`solve_cloudflare=False`).
### Fiabilidad

Turnstile no siempre entrega el token sin interaccion. El 24/11/2026, de 8
consultas reales seguidas, 6 respondieron en 15 a 20 s y 2 no recibieron token
(una por la API y otra por la CLI). Por eso, en modo headless:

- cada intento espera hasta 50 s (no los 120 s del sitio, porque nadie puede
  marcar la casilla);
- si aparece la casilla de Turnstile, el intento se corta en el acto;
- se prueba con una sesion de navegador nueva, hasta 3 veces dentro del
  `timeout` pedido;
- si ninguna obtiene respuesta se devuelve `requires_interaction`, indicando si
  Cloudflare mostro la casilla.

Con `--show-browser` hay un solo intento y se espera lo mismo que el sitio
(120 s) para que la persona pueda marcar la casilla.

## Flujo

1. Crear una sesion temporal de navegador.
2. Abrir el portal oficial.
3. Completar `input[name="placa"]`.
4. Pulsar Consultar (el sitio obtiene el token de Turnstile en este paso).
5. Observar `GET /consultas/placa/{placa}`, hasta 135 s.
6. Validar el criterio, las fuentes y la lista de documentos.
7. Cerrar la sesion sin guardar cookies.

## Contrato

`data` contiene:

| Campo | Significado |
|---|---|
| `encontrado` | La fuente entrego al menos un documento |
| `criterio` | Tipo y valor usado para la consulta |
| `fuentes` | Fuentes oficiales consultadas y si respondieron |
| `documentos` | Documentos e infracciones publicados por el portal |
| `capture` | Metodo y fecha de captura |

La consulta es referencial y no constituye una constancia de no adeudo.

## Estados

- `success`: existen documentos.
- `not_found`: el portal devolvio una lista vacia.
- `requires_interaction`: Turnstile o el navegador requieren accion.
- `unavailable`: el portal bloqueo o fallo la sesion.
- `parse_error`: la respuesta no coincide con el contrato esperado.

## Uso

```powershell
uv run obd-consultas query sutran B8T117 --stealth --timeout 180
```

Si Turnstile exige accion manual:

```powershell
uv run obd-consultas query sutran B8T117 --stealth --show-browser --timeout 180
```

Desde la API:

```json
{"source":"sutran","plate":"B8T117","timeout":180}
```

en `POST /v1/queries/stealth`, seguida de polling en `/v1/jobs/{job_id}`.
