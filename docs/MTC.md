# MTC: revisión técnica vehicular

## Evidencia del portal

Inspeccionado el 23 de noviembre de 2026 en el HTML y JavaScript publico de:

- https://portal.mtc.gob.pe/reportedgtt/form/frmconsultaplacaitv.aspx
- https://rec.mtc.gob.pe/Citv/ArConsultaCitv
- https://rec.mtc.gob.pe/Scripts/CITV/ConsultaCITVConfig.js

La URL original redirige a `rec.mtc.gob.pe`. El formulario publica su logica en
`ConsultaCITVConfig.js`:

```text
GET /CITV/refrescarCaptcha
GET /CITV/JrCITVConsultarFiltro?pArrParametros=1|PLACA||CAPTCHA
```

El primer endpoint entrega una imagen PNG en base64 y asocia la respuesta a una
cookie `ASP.NET_SessionId`. El segundo recibe el tipo de busqueda (`1` = placa),
la placa y el codigo que escribio el usuario. La respuesta es JSON:

```json
{
  "orStatus": true,
  "orResult": ["[ { ...registro... } ]"],
  "orCodigo": ""
}
```

`orResult` contiene hasta tres registros: ultimo, penultimo y antepenultimo
documento registrado. Un captcha incorrecto devuelve `orStatus: false` y
`orCodigo: "-1"`.

## Captcha: modo desatendido con OCR local

MTC usa un captcha numerico de seis digitos. El modo desatendido abre una sesion
HTTP temporal, pide una imagen nueva a `/CITV/refrescarCaptcha` y la lee con
`ddddocr` (OCR local, sin servicios externos). Solo acepta lecturas de seis
digitos. Si el portal rechaza el codigo, repite con una imagen nueva hasta cinco
veces; cada captcha se usa una sola vez y no se guarda.

```text
1. GET /Citv/ArConsultaCitv              -> cookies de la sesion
2. GET /CITV/refrescarCaptcha            -> imagen base64
3. OCR local                             -> codigo de 6 digitos
4. GET /CITV/JrCITVConsultarFiltro       -> respuesta JSON oficial
5. Normalizacion y cierre de la sesion
```

En una prueba de cinco captchas reales, cuatro fueron aceptados a la primera y
el quinto era ruido no numerico que se descarto antes de enviarlo. Con los
reintentos, el flujo desatendido suele completarse en el primer intento.

El modo asistido sigue disponible como respaldo: abre Edge/Chrome visible, una
persona lee el captcha y el conector lee la respuesta. Se usa con
`--interactive` o `/v1/queries/assisted`.

**Uso responsable:** automatizar un captcha puede estar fuera de los terminos
del portal. Este conector hace una consulta por peticion, con reintentos
limitados y sin guardar imagenes ni cookies. No lo uses para consultas masivas.

## Datos normalizados

`data` contiene:

| Campo | Significado |
|---|---|
| `encontrado` | La fuente devolvio registros |
| `vigente` | Registro con `ESTADO = VIGENTE`, o `null` |
| `registros` | Lista con ultimo, penultimo y antepenultimo documento |
| `capture` | `method` (`browser_api` o `browser_dom`) y `captured_at` |

Cada registro contiene `posicion`, `etiqueta` (`ULTIMO`, `PENULTIMO`,
`ANTEPENULTIMO`), `empresa`, `direccion`, `placa`, `numero_certificado`,
`tipo_documento`, `vigencia_desde`, `vigencia_hasta`, `resultado`, `estado`,
`ambito`, `tipo_servicio` y `observaciones`.

Las fechas se entregan como `AAAA-MM-DD`. Se des escapan entidades HTML del
nombre de la empresa certificadora. La placa de cada registro se compara con la
consultada; si no coincide, el resultado es `parse_error`.

## Estados

| Situacion | Estado |
|---|---|
| Respuesta con registros | `success` |
| `orStatus: true` sin registros | `not_found` |
| Captcha rechazado tras los reintentos | `requires_interaction` |
| Falta la dependencia de OCR | `unavailable` con instruccion de `uv sync` |
| Error HTTP del portal | `unavailable` |
| Formato inesperado | `parse_error` |

Un error nunca se interpreta como "sin revision tecnica".

## Uso

Desatendido (recomendado, igual que SOAT y SUNARP):

```powershell
uv run obd-consultas query mtc TU_PLACA --stealth --timeout 180
```

Asistido (una persona lee el captcha en el navegador visible):

```powershell
uv run obd-consultas query mtc TU_PLACA --interactive --browser chrome
```

Desde una APK, el mismo puente que las demas fuentes:

```powershell
$body = @{ source='mtc'; plate='ABC123'; timeout=180 } | ConvertTo-Json
$job = Invoke-RestMethod http://127.0.0.1:8000/v1/queries/stealth -Method Post -ContentType 'application/json' -Body $body
Invoke-RestMethod "http://127.0.0.1:8000$($job.poll_url)"
```

Ver [API.md](API.md).

## Limites y privacidad

- El OCR puede fallar. Si no obtiene un codigo valido tras cinco intentos, el
  resultado es `requires_interaction`; el modo asistido queda como respaldo.
- La dependencia `ddddocr` se instala con `uv sync` y ejecuta el modelo en la PC,
  sin enviar imagenes a ningun servicio externo.
- Solo se muestran los tres documentos mas recientes, no un historial completo.
- La direccion de la certificadora y la placa son datos publicos del portal; no
  se registran en logs ni se guardan en disco.
- Cada consulta usa una sesion HTTP nueva; no persiste cookies ni captchas. En
  el modo asistido, el navegador tambien es temporal.
- Un cambio de selectores o de formato de fecha puede requerir ajustes.

## Pruebas

Los fixtures son sinteticos. Se verifican los tres registros, el estado vigente,
las fechas, la placa que no coincide, el captcha invalido, la lista vacia, los
errores HTTP, el respaldo DOM y los dobles del navegador. El flujo real se valido
el 23/11/2026 con una placa autorizada: OCR local, tres registros normalizados y
tambien el modo asistido con captcha leido en pantalla. Los datos de prueba no se
guardaron.
