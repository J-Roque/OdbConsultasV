# SAT de Lima: orden de captura

Estado: **parcial**. El caso "sin orden de captura" se valido con una consulta
real el 24/11/2026; el caso "con orden" aun no se vio en real.

## Acceso

- `https://www.sat.gob.pe/` redirige a `https://www.gob.pe/satlima`, que respondio
  HTTP 418 ("Acceso restringido") al navegador integrado.
- La consulta funciona entrando directo a
  `https://www.sat.gob.pe/VirtualSAT/modulos/Capturas.aspx`.

## Formulario

ASP.NET WebForms, `POST` a la misma URL.

| Campo | Nombre | Notas |
|---|---|---|
| Placa | `ctl00$cplPrincipal$txtPlaca` | Texto, maximo 10 caracteres |
| Codigo de seguridad | `ctl00$cplPrincipal$txtCaptcha` | Texto, maximo 10 caracteres |
| Enviar | `ctl00$cplPrincipal$CaptchaContinue` | Submit |
| Refrescar captcha | `ctl00$cplPrincipal$ibtnRefresh` | Image button |
| Estado | `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION`, `__EVENTTARGET`, `__EVENTARGUMENT` | Ocultos, se leen del GET previo |

Captcha: imagen de `controles/JpegImage_VB.aspx?r=<aleatorio>`, unos 96x32 px,
4 caracteres alfanumericos sobre fondo con ruido. No hay reCAPTCHA ni Turnstile.

La pagina tiene una segunda pestana, "Internamiento de vehiculos" (deposito
vehicular), que podria ser otra fuente util.

## Conector (experimental)

`infrastructure/sat_stealth.py`, igual que MTC: sesion HTTP, GET para leer los
campos ocultos y la imagen, lectura local del captcha (`ddddocr`, 4 a 6 letras o
numeros) y POST con la placa. Si el portal rechaza el codigo, reintenta con el
captcha nuevo de la misma respuesta, hasta 5 veces.

## Respuesta real (24/11/2026)

Consulta por la API (`POST /v1/queries/stealth`) con una placa autorizada: el
OCR leyo el captcha y el SAT devolvio la misma pagina con el resultado en
estas etiquetas:

| Elemento | Contenido |
|---|---|
| `ctl00_cplPrincipal_lblMensajeVacio` | "El vehiculo de placa ... no tiene orden de captura en la provincia de Lima." |
| `ctl00_cplPrincipal_lblFecha` | "Informe actualizado al DD/MM/AAAA" |
| `ctl00_cplPrincipal_lblMensajeCapcha` | Vacio; aqui aparece el error si el codigo es incorrecto |
| `ctl00_cplPrincipal_divCapturas` | Contenedor del informe; sin tabla cuando no hay orden |

La pagina viene en UTF-8. El HTML crudo no se versiona (trae la placa).

## Parser

`providers/sat.py`:

- `lblMensajeCapcha` con texto: captcha rechazado, se reintenta.
- Tabla dentro de `divCapturas`: `success`, `tiene_orden_captura: true`, cada
  fila en `ordenes[]` (`detalle` y `campos`). **Provisional**: no se vio en real.
- `lblMensajeVacio` con "no tiene orden": `not_found`, `tiene_orden_captura: false`.
- `lblFecha`: `actualizado_al` en ISO.
- Cualquier otra pagina: `parse_error`, nunca `not_found`.

Con `OBD_DEBUG_DIR` definido se guarda el HTML crudo de cada respuesta.

```powershell
uv run obd-consultas query sat TU_PLACA --stealth
```

Pendiente:

1. Ver una respuesta real **con** orden de captura para confirmar la tabla.
2. Medir cuantas veces acierta la lectura del captcha.
3. Revisar los terminos de uso del SAT antes de automatizar la consulta.

## Contrato que espera la app ObdScanner

`tiene_orden_captura` (booleano) y `ordenes[].detalle`. Ver
[COBERTURA-APP.md](COBERTURA-APP.md).
