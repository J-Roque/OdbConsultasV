# SAT de Lima: orden de captura

Estado: **por validar**. Inspeccion inicial del 24/11/2026; aun no se envio
ninguna consulta ni se vio una respuesta.

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

## Enfoque probable

Igual que MTC: sesion HTTP, GET para leer los campos ocultos y la imagen,
lectura local del captcha y POST con la placa. Pendiente:

1. Ver una respuesta real (con y sin orden de captura) para definir el parser.
2. Medir cuantas veces acierta la lectura del captcha.
3. Revisar los terminos de uso del SAT antes de automatizar la consulta.

## Contrato que espera la app ObdScanner

`tiene_orden_captura` (booleano) y `ordenes[].detalle`. Ver
[COBERTURA-APP.md](COBERTURA-APP.md).
