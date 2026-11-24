# Callao: papeletas de transito

Estado: **Parcial**. La consulta desatendida esta validada con una placa sin
papeletas (23/11/2026). Falta ver un caso real con papeletas para confirmar las
columnas y marcar la fuente como implementada (`implemented=false` por ahora).

## Portal

- <https://pagopapeletascallao.pe/>, de la Municipalidad Provincial del Callao.
  Es el enlace que publica la propia municipalidad en
  [gob.pe/municallao](https://www.gob.pe/municallao) ("Consultar papeletas de
  transito"), aunque el dominio no sea `.gob.pe`.
- Busqueda por **Numero de Placa** o **Numero de Papeleta**.
- La pagina tambien tiene un formulario de pago que pide DNI, nombre, telefono,
  correo y direccion. El conector **no lo usa**: solo envia la placa.

## Formulario

Formulario Laravel `POST /buscar`:

| Campo | Valor |
|---|---|
| `_token` | Oculto, del formulario |
| `captcha_key` | Oculto, del formulario |
| `tipo_busqueda` | `1` (placa) |
| `valor_busqueda` | Placa sin guiones |
| `captcha` | Codigo de 3 caracteres |

El captcha llega como PNG en linea (`<img alt="captcha" src="data:image/png;base64,...">`).
El HTML deja formularios e imagenes antiguos dentro de comentarios: el parser
los quita antes de leer.

## Respuestas observadas

- **Codigo incorrecto:** redireccion a
  `/?error=Error al ingresar el codigo de seguridad`.
- **Sin papeletas:** `<p class="alert alert-info">No hay resultados para mostrar.</p>`.
- **Con papeletas (sin validar):** tabla `#dataTable`. Segun el script del portal,
  la fila tiene una casilla, la placa, el codigo de infraccion, el numero de
  papeleta, el importe (columna 7) y la cuota (columna 8). El parser lee las
  columnas desde el `thead`.

## Flujo del conector (`callao_stealth.py`)

1. GET del formulario: trae `_token`, `captcha_key` y el captcha.
2. ddddocr lee el codigo; si no son 3 letras o numeros, pide otro formulario.
3. POST con la placa y el codigo.
4. Si el portal rechaza el codigo, repite con un formulario nuevo (hasta 5 veces
   dentro del `timeout`).

Con `OBD_DEBUG_DIR` definido se guarda el HTML de la respuesta final
(`callao-<placa>-<fecha>.html`) para ajustar el parser.

## Contrato (`data`)

| Campo | Tipo | Nota |
|---|---|---|
| `tiene_papeletas` | bool | |
| `papeletas` | lista de objetos | Filas de `#dataTable`, claves en snake_case. Se omiten columnas cuyo titulo sugiere datos personales (nombre, infractor, conductor, propietario, DNI, documento, direccion). |
| `mensaje` | texto o null | Aviso del portal cuando no hay papeletas |

Estados:

- `success`: la tabla tiene filas de la placa consultada.
- `not_found`: aviso "No hay resultados para mostrar".
- `requires_interaction`: no se pudo leer un captcha valido dentro del tiempo.
- `unavailable`: error HTTP o fallo de la sesion.
- `parse_error`: otro aviso del portal, pagina desconocida, filas de otra placa
  o columnas inesperadas. Nunca se convierte en `not_found`.

## Pendiente

- Validar con una placa que tenga papeletas (columnas reales e importes).
