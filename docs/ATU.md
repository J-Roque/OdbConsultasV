# ATU: infracciones de transporte (Lima y Callao)

Estado: **Parcial**. La consulta desatendida esta validada con una placa sin
infracciones (23/11/2026). Falta ver un caso real con infracciones para confirmar
las columnas y marcar la fuente como implementada (`implemented=false` por ahora).

## Portal

- Pasarela de pagos: <https://pasarela.atu.gob.pe/>, menu **Consulta y Pago de
  Infracciones**.
- Busqueda **Por Placa** (6 caracteres) o **Por Acta Fiscalizacion**.
- Solo incluye actas impuestas por la ATU desde el 23/10/2019.
- No pide cuenta ni datos personales para consultar.

## Como responde

- La pagina es una SPA (Materialize + SweetAlert2). Al pulsar BUSCAR obtiene un
  token de **reCAPTCHA v3 invisible** y llama a su API con
  `{tipoBusqueda, filtro, captcha}`.
- La API responde **cifrada** (CryptoJS, `U2FsdGVkX1...`) y la llamada sale de un
  worker. Por eso el conector **no usa la API**: lee lo que la pagina muestra.
- Sin infracciones aparece un aviso de SweetAlert2 con icono `info`:
  "La placa consultada no cuenta con infraccion registrada al momento de la consulta."
- Con infracciones se llena una tabla con estas columnas:
  `Ver Acta`, `Seleccionar`, `Placa`, `Tipo Acta`, `Reglamento`,
  `Acta Fiscalizacion`, `Falta`, `Tipo Infractor`, `Fecha Infraccion`,
  `¿Reincidencia?`, `Importe`, `Gastos/Costas`, `Total Deuda`, `Total Pagado`,
  `Total a Pagar`, `Estado`.
- La tabla pagina de 10 en 10 y muestra "Registros x - y de N".

## Flujo del conector (`atu_stealth.py`)

1. Abre la pasarela con el navegador sigiloso (sin ventana) y cierra el comunicado.
2. Entra a **Consulta y Pago de Infracciones** y elige **Por Placa**.
3. Escribe la placa y pulsa BUSCAR: el propio sitio ejecuta su reCAPTCHA v3.
4. Espera hasta 45 s a que aparezca el aviso o filas reales en la tabla.
5. Si la pagina no muestra nada, prueba una sesion nueva (2 en total) dentro del
   `timeout`.

El conector no lee, genera ni reutiliza el token de reCAPTCHA.

## Contrato (`data`)

| Campo | Tipo | Nota |
|---|---|---|
| `tiene_infracciones` | bool | |
| `infracciones` | lista de objetos | Una fila por acta. Claves en snake_case: `placa`, `tipo_acta`, `reglamento`, `acta_fiscalizacion`, `falta`, `tipo_infractor`, `fecha_infraccion`, `reincidencia`, `importe`, `gastos_costas`, `total_deuda`, `total_pagado`, `total_a_pagar`, `estado`. Los montos quedan como texto del portal. |
| `total_registros` | int | Segun el contador de la tabla |
| `completo` | bool | `false` si habia mas de una pagina: hoy solo se lee la primera |
| `mensaje` | texto o null | Aviso del portal cuando no hay infracciones |

Estados:

- `success`: hay filas para la placa consultada.
- `not_found`: aviso "no cuenta con infraccion registrada".
- `requires_interaction`: la pagina no mostro resultado o el aviso habla de
  captcha o verificacion.
- `unavailable`: aviso de error o advertencia del portal, o fallo del navegador.
- `parse_error`: aviso desconocido, filas de otra placa o columnas inesperadas.
  Nunca se convierte en `not_found`.

## Privacidad

La tabla no muestra nombres ni documentos de personas: `Tipo Infractor` es un rol
(por ejemplo, transportista). No se guardan ni registran las filas.

## Pendiente

- Validar con una placa que tenga infracciones (columnas y montos reales).
- Leer las paginas siguientes cuando haya mas de 10 actas.
