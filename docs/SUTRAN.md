# SUTRAN: papeletas e infracciones por placa

## Evidencia

Inspeccionado el 23 de noviembre de 2026 en:

- https://digital.sutran.gob.pe/
- https://api.dig.sutran.gob.pe/consultas/placa/{placa}

El portal acepta una placa en el campo `placa`, resuelve Turnstile en el
navegador y consulta una API publica que exige el contexto de la sesion
en el navegador. Una consulta directa a la API sin esa sesion puede devolver
HTTP 403.

## Flujo

1. Crear una sesion temporal de navegador.
2. Abrir el portal oficial.
3. Completar `input[name="placa"]`.
4. Pulsar Consultar.
5. Observar `GET /consultas/placa/{placa}`.
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
