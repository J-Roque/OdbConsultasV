# SUNARP: consulta vehicular

## Evidencia del portal

Inspeccionado el 23 de noviembre de 2026 en el HTML y JavaScript publico de:

- https://consultavehicular.sunarp.gob.pe/
- https://consultavehicular.sunarp.gob.pe/consulta-vehicular/inicio

El portal es una aplicacion Angular 17. El formulario pide el numero de placa y
usa un widget de Cloudflare Turnstile. La aplicacion publica en su JavaScript la
ruta oficial que consume:

```text
POST https://api-gateway.sunarp.gob.pe:9443/sunarp/multiservicios/
     multiservicio-consvehicular/consulta/getDatosVehiculo
```

El cuerpo incluye `numPlaca`, `regPubId`, `oficRegId`, `ipAddress`, `appVersion`
y `dG9rZW4` (el token que genera el widget Turnstile). El proyecto no genera,
extrae ni reutiliza ese token: conduce el formulario oficial dentro del navegador
sigiloso y el propio widget genera el token.

La respuesta exitosa tiene esta forma:

```json
{
  "cod": 1,
  "mensaje": "Placa encontrada satisfactoriamente",
  "mensajeTxt": "Consulta Vehicular",
  "icon": "success",
  "model": {
    "imagen": "<PNG en base64>",
    "msgAlertaRobo": "",
    "sedes": [
      {
        "prefijo": "OR0101",
        "regPubId": "01",
        "oficRegId": "01",
        "nombre": "LIMA",
        "fgBaja": "0",
        "placa": "ABC123",
        "numPartida": "00000000"
      }
    ]
  }
}
```

Cuando la placa no existe, `cod` es `0`, `model` es `null` y `mensaje` indica
`No se ha encontrado la placa del vehiculo ingresado`. Cualquier otro `cod` o
mensaje se trata como indisponibilidad, nunca como ausencia de registros.

## Flujo implementado

`query sunarp PLACA --stealth` usa `infrastructure/sunarp_stealth.py`:

1. Abre un Chromium sigiloso con locale `es-PE` y resuelve el reto de Cloudflare.
2. Espera el formulario Angular, completa `#nroPlaca` y pulsa `Realizar Busqueda`.
3. Observa la respuesta JSON de `getDatosVehiculo`; si no la recibe, lee la
   tarjeta visible como respaldo.
4. Valida la imagen PNG, la placa de las sedes y el aviso de robo.
5. Cierra el navegador. Sin `--profile` no guarda cookies ni estado.

Turnstile no se resuelve siempre en la primera sesion. Con `--timeout` de 60
segundos o mas, el conector abre hasta **tres sesiones nuevas** antes de devolver
`requires_interaction`. Asi una sesion con captcha pendiente no falla la consulta
completa. Si agotan los intentos, el mensaje lo indica explicitamente.

Si Turnstile exige intervencion, el resultado es `requires_interaction`; no se
inventa un `not_found`. La API local mantiene `/v1/queries` en
`requires_interaction`, pero `POST /v1/queries/stealth` ejecuta este mismo flujo
en segundo plano y publica la tarjeta en `GET /v1/jobs/{id}` para una APK. Ver
[API.md](API.md).

## Datos normalizados

`data` contiene:

| Campo | Significado |
|---|---|
| `encontrado` | La fuente devolvio una tarjeta para la placa |
| `alerta_robo` | Texto de `msgAlertaRobo`, o `null` si esta vacio |
| `sedes` | Sedes registrales con placa y numero de partida |
| `plate_verified` | La placa de las sedes coincide con la consultada |
| `tarjeta` | Imagen oficial de la tarjeta TIVE |
| `vehiculo` | Campos leidos de la imagen con OCR local |
| `capture` | `method` (`stealth_api` o `stealth_dom`) y `captured_at` |

Cada sede contiene `prefijo`, `reg_pub_id`, `ofic_reg_id`, `nombre`, `fg_baja`,
`placa` y `num_partida`. Los campos que la fuente no entrega quedan en `null`.

`tarjeta` contiene `formato` (`png`), `ancho`, `alto`, `sha256` y `base64`. Es la
imagen oficial del portal: sigue siendo la fuente de verdad y puede decodificarse
para mostrarla o guardarla.

`vehiculo` contiene `placa`, `serie`, `vin`, `motor`, `color`, `marca`, `modelo`,
`placa_vigente`, `placa_anterior`, `estado`, `anotaciones`, `sede`, `anio_modelo`,
`propietarios` y `placa_coincide`. Cada campo leido trae `valor` y `confianza`
(0 a 1), mas `ocr: "rapidocr"`. Los campos que la tarjeta no muestra quedan en
`null` con `confianza: null`. Si el OCR falla, `vehiculo.disponible` es `false` y
se conserva la imagen. Un campo con baja confianza no se presenta como dato
oficial.

`data.capture.method` indica la procedencia:

- `stealth_api`: respuesta JSON observada en el navegador sigiloso.
- `stealth_dom`: imagen leida del resultado visible cuando la API no se pudo observar.

En el respaldo DOM la tabla de sedes puede no estar desplegada. En ese caso
`plate_verified` es `false` y el mensaje lo advierte; la imagen sigue siendo la
respuesta oficial del portal.

## Privacidad y limites

La tarjeta TIVE puede contener nombres de propietarios. No se registran placas,
propietarios, cookies ni cuerpos de respuesta en logs; la CLI imprime el JSON
solo porque el usuario lo solicito. No se guarda historial ni cache.

- SUNARP no publica una ficha JSON con los datos del vehiculo: entrega la imagen.
  `vehiculo` es una lectura local con RapidOCR, no un certificado oficial.
- RapidOCR ejecuta modelos ONNX en la PC; no envia imagenes a servicios externos.
  Un cambio de diseno de la tarjeta puede requerir ajustar `sunarp_ocr.py`.
- `vin` y `anio_modelo` pueden quedar vacios si la tarjeta no los muestra; no se
  inventan valores para completarlos.
- La tabla de sedes solo se muestra cuando hay mas de una sede; el respaldo DOM
  no siempre puede verificar la placa.
- Turnstile puede exigir intervencion. Se devuelve `requires_interaction` o
  `unavailable`; nunca `not_found`.
- La consulta se valido el 23/11/2026 con una placa autorizada. Los datos de la
  prueba no se guardaron y no se usan como fixtures.

## Pruebas

Los fixtures son sinteticos. Se verifica la respuesta exitosa, el aviso de robo,
la placa que no coincide, la imagen invalida o que no es PNG, las sedes
incompletas, el mensaje de placa no encontrada, los errores HTTP, el respaldo DOM,
los dobles del navegador (timeout, captcha, error y dependencia faltante) y el
parseo de los campos TIVE con resultados de OCR simulados.

```powershell
uv run --extra dev python -m unittest discover -s tests -v
```

## Uso

```powershell
uv run obd-consultas query sunarp TU_PLACA --stealth --timeout 180
uv run obd-consultas query sunarp TU_PLACA --stealth --show-browser
uv run obd-consultas query sunarp TU_PLACA --stealth --real-chrome
```
