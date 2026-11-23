# API local para clientes (APK)

La API corre en la PC que tiene Python, Scrapling y los navegadores. Un cliente
como una APK solo hace HTTP; el navegador sigiloso se ejecuta siempre en la PC.

## Iniciar

```powershell
Copy-Item .env.example .env
uv run obd-consultas token        # copia el valor a OBD_API_TOKEN en .env
uv run obd-consultas serve
```

Por defecto escucha en `http://127.0.0.1:8000`. Para que el telefono se conecte
por LAN:

```powershell
uv run obd-consultas serve --host 0.0.0.0
```

## Seguridad

| Control | Comportamiento | Variable |
|---|---|---|
| Token | Obligatorio siempre, minimo 32 caracteres, comparado en tiempo constante. Sin token valido `/v1/*` responde **503** (fail-closed), aunque la app se arranque con otro comando de Uvicorn. | `OBD_API_TOKEN` |
| Limite de peticiones | Por IP, ventana de 60 s, se aplica antes del token (frena fuerza bruta). Responde **429** con `Retry-After`. | `OBD_API_RATE_LIMIT` (30) |
| Consultas simultaneas | Trabajos `pending`/`running` a la vez. Excedido: **429**. | `OBD_API_MAX_ACTIVE_JOBS` (5) |
| Documentacion | `/docs`, `/redoc` y `/openapi.json` responden 404. | `OBD_API_DOCS=1` |
| Consulta asistida | `POST /v1/queries/assisted` abre un navegador visible en la PC: responde **403**. | `OBD_API_ASSISTED=1` |
| Cabeceras | `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`; sin cabecera `Server`. | - |
| Logs | Sin access log: no se registran placas, tokens ni respuestas. | - |
| TLS | `--ssl-certfile` y `--ssl-keyfile`, o un proxy inverso con HTTPS. Sin TLS, `serve` advierte al exponer fuera de loopback. | - |

`/health` es la unica ruta publica. Sin TLS la API sirve solo para una red de
confianza: cualquiera que intercepte el trafico ve el token. **No exponerla a
Internet** sin HTTPS y sin revisar [SECURITY.md](../SECURITY.md).

En la APK, no escribas el token en el codigo fuente: guardalo con
`EncryptedSharedPreferences` (o Android Keystore) y pidelo al usuario la primera vez.

## Endpoints

| Metodo | Ruta | Uso |
|---|---|---|
| GET | `/health` | `{"status":"ok"}` |
| GET | `/v1/sources` | Fuentes y estado del conector |
| POST | `/v1/queries` | Contrato basico: **no consulta**, devuelve `requires_interaction` |
| POST | `/v1/queries/stealth` | Encola la consulta desatendida (SOAT, SUNARP, MTC o SUTRAN) y devuelve un `job_id` |
| POST | `/v1/queries/assisted` | Encola la consulta asistida (SOAT o MTC) con navegador visible |
| GET | `/v1/jobs/{job_id}` | Estado y resultado del trabajo |

## Flujo recomendado para la APK

1. `POST /v1/queries/stealth` con:

```json
{
  "source": "sunarp",
  "plate": "ABC123",
  "timeout": 180
}
```

`source` admite `soat`, `sunarp` o `mtc`. `timeout` va de 10 a 600 segundos.
`sutran` acepta el cuerpo pero es experimental: su portal exige un token de
Turnstile que hoy no se obtiene de forma desatendida, por lo que devuelve
`requires_interaction`. Ver [SUTRAN.md](SUTRAN.md).
El caso de MTC se resuelve con OCR local; el campo `browser` no aplica.
`/v1/queries/assisted` permite `soat` o `mtc` y abre el navegador visible:

```json
{"source": "mtc", "plate": "ABC123", "timeout": 180, "browser": "msedge"}
```

2. La respuesta es HTTP 202:

```json
{
  "job_id": "dafca094b6f8478aba6b4e5750756a86",
  "state": "pending",
  "poll_url": "/v1/jobs/dafca094b6f8478aba6b4e5750756a86"
}
```

3. Hacer polling de `poll_url` cada 2 o 3 segundos hasta que `state` sea `done`:

```json
{
  "job_id": "dafca...",
  "state": "done",
  "result": {
    "source": "sunarp",
    "plate": "ABC123",
    "status": "success",
    "source_url": "https://consultavehicular.sunarp.gob.pe/",
    "message": "Consulta obtenida del portal SUNARP...",
    "data": { "...": "..." },
    "queried_at": "2026-11-23T19:25:47Z"
  }
}
```

Mientras tanto `state` puede ser `pending` o `running`. El conector tarda
normalmente entre 20 y 60 segundos porque abre un navegador y conduce el
formulario oficial. Solo se ejecuta una consulta sigilosa a la vez; las demas
esperan su turno.

4. Leer `result.status` antes que el HTTP. Los estados son `success`,
   `not_found`, `requires_interaction`, `unavailable`, `parse_error` y
   `not_implemented`. HTTP 200 significa "resultado estructurado", no exito.

## Resultado de SUNARP

`data` contiene:

```json
{
  "encontrado": true,
  "alerta_robo": null,
  "sedes": [
    {
      "prefijo": "OR0101",
      "reg_pub_id": "01",
      "ofic_reg_id": "01",
      "nombre": "LIMA",
      "fg_baja": "0",
      "placa": "ABC123",
      "num_partida": "00000000"
    }
  ],
  "plate_verified": true,
  "tarjeta": {
    "formato": "png",
    "ancho": 540,
    "alto": 680,
    "sha256": "...",
    "base64": "..."
  },
  "capture": {
    "method": "stealth_api",
    "captured_at": "2026-11-23T19:25:47Z"
  }
}
```

`tarjeta.base64` es la tarjeta TIVE oficial. Decodificala en la APK para mostrarla.
Puede contener nombres de propietarios: no la registres en logs ni la envies a
terceros. Ver [SUNARP.md](SUNARP.md).

El resultado de SOAT tiene certificados en `data.certificados` y el vigente en
`data.soat_vigente`. Ver [SOAT.md](SOAT.md).

El resultado de MTC trae hasta tres documentos de revision tecnica en
`data.registros`, con etiquetas `ULTIMO`, `PENULTIMO` y `ANTEPENULTIMO`, y el
vigente en `data.vigente`. `data.capture.method` es `stealth_ocr` en el modo
desatendido. Ver [MTC.md](MTC.md).

## Ejemplo Kotlin (OkHttp)

```kotlin
val base = "http://192.168.1.10:8000"
val token = secureStorage.getString("obd_token")  // nunca en el codigo fuente
val client = OkHttpClient()

val body = """{"source":"sunarp","plate":"ABC123","timeout":180}"""
    .toRequestBody("application/json".toMediaType())

val request = Request.Builder()
    .url("$base/v1/queries/stealth")
    .header("X-OBD-Token", token)
    .post(body)
    .build()

val job = client.newCall(request).execute().use { response ->
    if (!response.isSuccessful) error("HTTP ${response.code}")
    response.body!!.string()
}
// parsear job_id / poll_url y consultar GET base + poll_url hasta state == "done"
```

## Limites y errores

| Situacion | Respuesta |
|---|---|
| Token ausente o incorrecto | 401 |
| API sin `OBD_API_TOKEN` valido | 503 |
| Consulta asistida deshabilitada | 403 |
| Demasiadas peticiones o consultas en curso | 429 + `Retry-After` |
| Fuente, placa o timeout invalidos | 422 |
| `job_id` desconocido | 404 |
| Error inesperado del conector | Trabajo `done` con `result.status = unavailable` |
| Reinicio del servidor | Los trabajos en memoria desaparecen |

Se conservan como maximo los ultimos 100 trabajos. No hay persistencia ni
historial: si la APK necesita guardar la tarjeta, debe hacerlo en el dispositivo
con el consentimiento del usuario.
