# SOAT: investigacion e implementacion

## Evidencia del portal

Inspeccionado el 20 de noviembre de 2026 en el HTML y JavaScript publico de:

- https://www.apeseg.org.pe/consultas-soat/
- https://www.apeseg.org.pe/wp-content/plugins/apeseg-consulta-soat/assets/dist/consulta-soat.js?ver=1.1.2

El formulario publica `data-endpoint` con la ruta `/wp-json/apeseg-soat/v1/placa/`.
Su JavaScript envia una consulta GET con la placa, usando el token generado por el widget
Turnstile en el encabezado `X-Turnstile-Token`. El proyecto no genera, extrae ni reutiliza
ese token: el formulario del portal gestiona la verificacion y la consulta.

El frontend lee `placa` y `certificados`. Los certificados incluyen `Estado`,
`NombreCompania`, `NumeroPoliza`, `FechaInicio` y `FechaFin`, entre otros campos.
Considera una lista vacia o el literal `NombreCompania: No encontrada` como ausencia
de certificados. Este esquema se valido con una respuesta real obtenida por el modo
desatendido; los datos de la prueba no se guardaron.

## Flujos implementados

### Desatendido (recomendado)

`query soat PLACA --stealth` usa `infrastructure/soat_stealth.py` y Scrapling:

1. Abre un Chromium sigiloso con locale `es-PE` y resuelve el reto de Cloudflare.
2. Completa la placa y pulsa el boton normal del portal.
3. Observa la respuesta JSON de la API o, como respaldo, lee el resultado visible.
4. Despliega el historial cuando existe y normaliza los certificados.
5. Cierra el navegador. Sin `--profile` no guarda cookies ni estado.

El modo sigiloso no extrae, reutiliza ni falsifica el token de Turnstile: lo genera
el propio formulario del portal. Si el reto o el resultado no llegan, devuelve
`requires_interaction` o `unavailable`; nunca inventa `not_found`.

### Asistido

1. CLI normaliza la placa y abre un navegador temporal (Edge o Chrome).
2. Completa la placa y envia el formulario normal del portal.
3. Si aparece una verificacion, el usuario la completa; el programa espera el resultado.
4. Lee el resultado visible y despliega el historial cuando existe.
5. Comprueba placa, numero de certificados y coherencia entre tarjeta principal e historial.
6. Normaliza los certificados, cierra el navegador y entrega JSON por consola.

Este flujo no depende de capturar una URL de respuesta exacta. La verificacion del
portal sigue siendo necesaria cuando este la exige. No se alteran tokens ni desafios.
La API mantiene `/v1/queries` en `requires_interaction` y no inicia navegadores;
`POST /v1/queries/stealth` ejecuta el conector desatendido en segundo plano para
clientes HTTP. Ver [API.md](API.md).

## Validacion con datos reales e importacion

Se recogio el resultado visible del navegador integrado para la placa autorizada y
Python proceso los ocho certificados: uno vigente, uno anulado y seis vencidos.
Los archivos locales estan en `artifacts/`, excluidos de Git. No se usan como fixtures.

```powershell
uv run obd-consultas import-soat artifacts/soat-B8T117.capture.json --plate B8T117
```

`import-soat` acepta capturas `apeseg-dom-v1`. No consulta la web: valida y procesa
un archivo. `data.capture.method=imported_browser_dom` y el mensaje de respuesta lo
indican. La URL declarada se comprueba por coherencia, pero no autentica el origen
de un archivo. No usar importaciones como prueba independiente o certificado oficial.

Se puede guardar la salida con `--output ruta.json`; el destino debe ser nuevo.
`captured_at` identifica la captura y `queried_at` el procesamiento de la respuesta;
la importacion no acredita una consulta nueva. La prueba desatendida desde Python no
queda validada por el exito de una importacion.

## Datos normalizados

`data` contiene `encontrado`, `vigente`, `soat_vigente` y `certificados`.
Cada certificado contiene estado, aseguradora, numero de poliza, vigencia desde/hasta,
tipo de certificado y uso/clase del vehiculo cuando estan disponibles.
Las fechas se entregan como `AAAA-MM-DD`. La vigencia reproduce el estado declarado
por la fuente, no una conclusion independiente sobre cobertura.

`data.capture.method` indica la procedencia: `stealth_api` (respuesta JSON del modo
sigiloso), `browser_dom` (resultado visible del modo asistido) o
`imported_browser_dom` (archivo importado). En el modo sigiloso `captured_at` es la
hora UTC de la captura. No es un certificado oficial ni acredita por si solo una
consulta nueva.

## Pruebas y limites

Los fixtures automatizados son sinteticos. Se verifica el historial, estados de
certificado, fechas invalidas, placas que no coinciden, respuestas inesperadas,
limites HTTP y filtrado de la ruta capturada. No se usa la placa real como fixture.
El modo sigiloso se prueba con dobles: respuesta JSON, respaldo DOM, aviso de
ausencia, timeout, error de navegador y dependencia faltante. La consulta real del
20/11/2026 valido el camino desatendido completo; no se guardaron sus datos.

Un cambio de formulario, ruta o formato puede requerir ajustes del conector.
Si la verificacion no se completa a tiempo se devuelve `requires_interaction`.
Una consulta denegada o ilegible nunca se interpreta como ausencia de SOAT.
El modo asistido no constituye un extractor desatendido.

## Resultado de los reintentos

Edge y Chrome no completaron la verificacion en el flujo asistido anterior.
El 20/11/2026 el modo desatendido con Scrapling obtuvo la respuesta real sin
intervencion y Python normalizo todos los certificados; los datos no se guardaron.
La captura y el resultado e2e del navegador integrado siguen en `artifacts/` y la
importacion sigue disponible. El exito valida el flujo desatendido actual, no el
modo asistido con Edge/Chrome. Ver [SCRAPLING.md](SCRAPLING.md).

## Prueba en navegador integrado

Se recargo APESEG, se escribio la placa y se pulso Consultar automaticamente.
El portal devolvio el certificado vigente y los ocho registros sin intervencion del
usuario. No se resolvio un desafio. Se reutilizo la sesion existente: esto no
comprueba el comportamiento en una sesion nueva. Tampoco valida Playwright local.
La captura y resultado estan en `artifacts/soat-B8T117-e2e.*.json`.
Los ocho registros fueron iguales a la lectura anterior. Python los proceso como
importacion. El siguiente paso es reproducir el comportamiento fuera del navegador
integrado sin asumir que sus condiciones se pueden trasladar al backend.
